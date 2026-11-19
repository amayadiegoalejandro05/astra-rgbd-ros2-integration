"""Muestra RGB y profundidad en vivo y mide correspondencias en píxeles."""

import argparse
from contextlib import nullcontext
from datetime import datetime
import json
from math import hypot
from pathlib import Path
from statistics import median
import sys
import time

import cv2
import numpy as np

from detectar_rostro import DetectorFrontal, DisparoPuerta
from emitir_xyz import xyz_optico
from enlace_clic_ros import abrir_enlace
from probar_rgb_depth import (
    abrir_parejas, cargar_api, dibujar_superposicion, intrinsecos_depth,
    leer_pareja, visualizar_depth,
)


ANCHO, ALTO = 640, 480
VENTANA = "Astra Pro - RGB y depth"
RAIZ = Path(__file__).resolve().parents[1]


class ProyeccionDepth:
    def __init__(self, matriz, intrinsecos):
        fx, fy, cx, cy = intrinsecos
        v, u = np.indices((ALTO, ANCHO), dtype=np.float32)
        # Precalcular la contribución de cada rayo a la matriz de proyección.
        rayos = np.stack(((u - cx) / fx, (v - cy) / fy, np.ones_like(u)), axis=-1)
        self.rayos_proyectados = rayos @ matriz[:, :3].astype(np.float32).T
        self.traslacion = matriz[:, 3].astype(np.float32)

    def aplicar(self, depth, con_origen=False):
        validos = depth > 0
        puntos = self.rayos_proyectados[validos] * (depth[validos, None] / np.float32(1000))
        puntos += self.traslacion
        delante = puntos[:, 2] > 0
        puntos = puntos[delante]
        uv = np.rint(puntos[:, :2] / puntos[:, 2:3])
        dentro = (
            (uv[:, 0] >= 0) & (uv[:, 0] < ANCHO) &
            (uv[:, 1] >= 0) & (uv[:, 1] < ALTO)
        )
        u, v = uv[dentro].astype(np.intp).T
        # Conservar la superficie más cercana si varios puntos caen en el mismo píxel.
        z_rgb = np.rint(puntos[dentro, 2] * 1000).clip(1, 65534).astype(np.uint16)
        if con_origen:
            # Codificar Z y el índice original para conservar ambos al resolver oclusiones.
            ids = np.flatnonzero(validos)[delante][dentro].astype(np.uint64)
            codigos = (z_rgb.astype(np.uint64) << 19) | ids
            buffer = np.full(ALTO * ANCHO, np.iinfo(np.uint64).max, dtype=np.uint64)
            np.minimum.at(buffer, v * ANCHO + u, codigos)
            validos_destino = buffer != np.iinfo(np.uint64).max
            z = np.zeros(buffer.shape, dtype=np.uint16)
            origen = np.full(buffer.shape, -1, dtype=np.int32)
            z[validos_destino] = buffer[validos_destino] >> 19
            origen[validos_destino] = buffer[validos_destino] & ((1 << 19) - 1)
            return z.reshape(ALTO, ANCHO), origen.reshape(ALTO, ANCHO)
        salida = np.full(ALTO * ANCHO, 65535, dtype=np.uint16)
        np.minimum.at(salida, v * ANCHO + u, z_rgb)
        salida[salida == 65535] = 0
        return salida.reshape(ALTO, ANCHO)


def medir(rgb_uv, depth_uv):
    dx, dy = depth_uv[0] - rgb_uv[0], depth_uv[1] - rgb_uv[1]
    return dict(rgb_uv=rgb_uv, depth_uv=depth_uv, dx_px=dx, dy_px=dy, error_px=hypot(dx, dy))


class Visor:
    def __init__(self, modo, carpeta, seleccion=None):
        self.modo = modo
        self.carpeta = carpeta
        self.pausa = False
        self.superponer = True
        self.pendiente = None
        self.medidas = []
        self.aviso = ""
        self.seleccion = seleccion

    def clic(self, evento, x, y, _flags, _param):
        if evento != cv2.EVENT_LBUTTONDOWN or not 0 <= y < ALTO or not 0 <= x < ANCHO:
            return
        if self.seleccion is not None:
            self.seleccion.clic(x, y)
            return
        if self.pendiente is None:
            # El primer clic fija la pareja que ya estaba en pantalla.
            if not self.pausa:
                self.pausa = True
                self.medidas.clear()
            self.pendiente = (x, y)
            self.superponer = True
            self.aviso = "Marca el mismo punto en depth sobre la superposicion."
        else:
            self.medidas.append(medir(self.pendiente, (x, y)))
            self.pendiente = None
            self.aviso = ""

    def dibujar(self, rgb, depth, overlay):
        imagen = np.zeros((ALTO + 104, ANCHO, 3), dtype=np.uint8)
        imagen[:ALTO] = overlay if self.superponer else rgb
        for i, medicion in enumerate(self.medidas, 1):
            u, v = medicion["rgb_uv"]
            ud, vd = medicion["depth_uv"]
            cv2.arrowedLine(imagen, (u, v), (ud, vd), (255, 180, 30), 1, tipLength=0.3)
            cv2.drawMarker(imagen, (u, v), (100, 255, 100), cv2.MARKER_CROSS, 13)
            cv2.drawMarker(imagen, (ud, vd), (255, 180, 30), cv2.MARKER_TILTED_CROSS, 13)
            cv2.putText(imagen, str(i), (u + 8, v - 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (100, 255, 100), 1)
        if self.pendiente is not None:
            cv2.drawMarker(imagen, self.pendiente, (100, 255, 100), cv2.MARKER_CROSS, 13)
        estado = "PAUSA" if self.pausa else "EN VIVO"
        z = int(depth[ALTO // 2, ANCHO // 2])
        detalle = self.aviso or "Clic en el borde RGB y luego en el borde depth."
        if self.medidas and not self.aviso:
            m = self.medidas[-1]
            detalle = (f"#{len(self.medidas)}   dX {m['dx_px']:+d} px   dY {m['dy_px']:+d} px"
                       f"   Error {m['error_px']:.1f} px   "
                       f"Mediana {median(p['error_px'] for p in self.medidas):.1f} px")
        lineas = [
            f"{estado}  |  {self.modo.upper()}  |  Centro {z or '--'} mm",
            detalle,
            "O RGB/superposicion   Espacio pausa/reanuda",
            "U deshace   S guarda medidas   Esc cierra",
        ]
        if self.seleccion is not None:
            lineas = self.seleccion.dibujar(imagen)
        for i, linea in enumerate(lineas):
            cv2.putText(imagen, linea, (10, ALTO + 22 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX,
                        0.52, (235, 235, 235), 1, cv2.LINE_AA)
        return imagen

    def guardar(self):
        if not self.medidas:
            self.aviso = "Marca al menos un par de puntos."
            return
        self.carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"medicion_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
        informe = {
            "modo": self.modo, "resolucion": [ANCHO, ALTO], "pares": self.medidas,
            "mediana_px": median(p["error_px"] for p in self.medidas),
        }
        with (self.carpeta / nombre).open("x", encoding="utf-8") as archivo:
            json.dump(informe, archivo, indent=2)
        self.aviso = f"Guardado   {nombre}"

    def tecla(self, tecla):
        if self.seleccion is not None and tecla in (ord("u"), ord("s")):
            return
        if tecla == ord(" "):
            self.pausa = not self.pausa
            if not self.pausa:
                self.medidas.clear()
                self.pendiente = None
                self.aviso = ""
        elif tecla == ord("o"):
            self.superponer = not self.superponer
        elif tecla == ord("u"):
            if self.pendiente is not None:
                self.pendiente = None
            elif self.medidas:
                self.medidas.pop()
            self.aviso = ""
        elif tecla == ord("s"):
            try:
                self.guardar()
            except OSError as error:
                self.aviso = f"No se pudo guardar: {error.strerror}"


def preparar_superposicion(rgb, depth):
    vista = visualizar_depth(depth)
    coloreada = cv2.applyColorMap(vista, cv2.COLORMAP_TURBO)
    validos = depth > 0
    overlay = rgb.copy()
    mezcla = cv2.addWeighted(rgb, 0.65, coloreada, 0.35, 0)
    overlay[validos] = mezcla[validos]
    return dibujar_superposicion(overlay, depth)


class SeleccionXYZ:
    def __init__(self, enlace, api, flujo):
        self.enlace = enlace
        self.api = api
        self.flujo = flujo
        self.fotograma = None
        self.marca = None
        self.xyz = None
        self.aviso = ""

    def punto(self, x, y):
        if self.fotograma is None:
            return None
        crudo, origen, sello = self.fotograma
        indice = origen[y, x]
        if indice < 0 or time.time_ns() - sello > 900_000_000:
            self.aviso = ("Ese pixel no tiene profundidad valida." if indice < 0
                          else "Imagen antigua. Pulsa Espacio para reanudar.")
            return None
        v, u = divmod(int(indice), ANCHO)
        try:
            xyz = xyz_optico(self.api, self.flujo, u, v, int(crudo[v, u]))
        except RuntimeError:
            self.aviso = "No se pudo calcular XYZ para ese pixel."
            return None
        return xyz, sello

    def clic(self, x, y):
        if not self.enlace.listo or self.enlace.pendiente is not None:
            return
        punto = self.punto(x, y)
        if punto is not None:
            xyz, sello = punto
            if self.enlace.enviar(xyz, sello):
                self.marca, self.xyz, self.aviso = (x, y), xyz, ""

    def dibujar(self, imagen):
        self.enlace.actualizar()
        coordenadas = "XYZ en el marco optico de profundidad"
        if self.xyz is not None:
            x, y, z = self.xyz
            coordenadas = f"X {x:+.3f} m    Y {y:+.3f} m    Z {z:.3f} m"
            cv2.drawMarker(imagen, self.marca, (90, 255, 90), cv2.MARKER_CROSS, 21, 2)
        return [coordenadas, self.enlace.estado[:75], self.aviso,
                "Clic envia un punto   O cambia vista   Espacio pausa   Esc cierra"]


class RostroXYZ(SeleccionXYZ):
    def __init__(self, enlace, api, flujo):
        super().__init__(enlace, api, flujo)
        self.detector = DetectorFrontal()
        self.disparo = DisparoPuerta()
        self.rectangulo = None

    def clic(self, x, y):
        # En modo rostro el mouse no puede accionar la puerta.
        pass

    def observar(self, rgb):
        self.rectangulo = self.detector.detectar(rgb)
        self.marca, self.xyz, self.aviso = None, None, ""
        punto = None
        if self.rectangulo is not None:
            x, y, ancho, alto = self.rectangulo
            self.marca = x + ancho // 2, y + alto // 2
            punto = self.punto(*self.marca)
            # El reproyectado puede dejar un hueco de un píxel en el centro.
            if punto is None:
                _, origen, _ = self.fotograma
                u, v = self.marca
                u0, v0 = max(0, u - 3), max(0, v - 3)
                yy, xx = np.nonzero(origen[v0:v + 4, u0:u + 4] >= 0)
                if len(xx):
                    cercano = np.argmin((xx + u0 - u)**2 + (yy + v0 - v)**2)
                    punto = self.punto(int(xx[cercano] + u0), int(yy[cercano] + v0))
            if punto is not None:
                self.xyz = punto[0]
        disponible = self.enlace.listo and self.enlace.pendiente is None
        z = self.xyz[2] if self.xyz is not None else None
        if self.disparo.observar(self.rectangulo is not None, z, time.monotonic(), disponible):
            if self.enlace.enviar(*punto):
                self.disparo.disparado()

    def dibujar(self, imagen):
        if self.rectangulo is not None:
            x, y, ancho, alto = self.rectangulo
            cv2.rectangle(imagen, (x, y), (x + ancho, y + alto), (90, 255, 90), 2)
        lineas = super().dibujar(imagen)
        if self.rectangulo is None:
            lineas[0] = "Buscando rostro frontal..."
        elif self.xyz is None:
            lineas[0] = "Rostro detectado. Centro sin profundidad valida."
        if not self.disparo.armado and self.enlace.pendiente is None:
            lineas[2] = "Alejate a 0.60 m o sal del encuadre para rearmar."
        elif self.enlace.pendiente is not None:
            lineas[2] = "Ciclo de puerta en curso. Apertura programada de 3 segundos."
        else:
            lineas[2] = "Activacion automatica a 0.50 m."
        lineas[3] = "O cambia vista   Espacio pausa   Esc cierra"
        return lineas


def ejecutar(args, matriz):
    api = cargar_api(args.sdk.resolve())
    canal = abrir_enlace(RAIZ, args.puerto, args.rostros) if args.enviar_ros or args.rostros else nullcontext()
    with abrir_parejas(api, args.rgb_index, args.modo == "nativo") as (camara, flujo), canal as enlace:
        tipo_seleccion = RostroXYZ if args.rostros else SeleccionXYZ
        seleccion = tipo_seleccion(enlace, api, flujo) if enlace is not None else None
        visor = Visor(args.modo, RAIZ / "resultados" / "visor", seleccion)
        proyeccion = None
        if matriz is not None:
            proyeccion = ProyeccionDepth(matriz, intrinsecos_depth(api, flujo))
        cv2.namedWindow(VENTANA, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(VENTANA, visor.clic)
        try:
            while True:
                if not visor.pausa:
                    rgb, depth = leer_pareja(api, camara, flujo)
                    if seleccion is not None:
                        sello = time.time_ns()
                        crudo = depth
                        depth, origen = proyeccion.aplicar(crudo, con_origen=True)
                        seleccion.fotograma = (crudo, origen, sello)
                        if args.rostros:
                            seleccion.observar(rgb)
                    elif proyeccion is not None:
                        depth = proyeccion.aplicar(depth)
                    overlay = preparar_superposicion(rgb, depth)
                cv2.imshow(VENTANA, visor.dibujar(rgb, depth, overlay))
                tecla = cv2.waitKey(15) & 0xFF
                if tecla == 27 or cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                    break
                visor.tecla(tecla)
        finally:
            cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--rgb-index", type=int, default=1)
    parser.add_argument("--modo", choices=("experimental", "nativo", "crudo"),
                        default="experimental")
    parser.add_argument("--calibracion", type=Path,
                        default=RAIZ / "resultados" / "calibracion_caja_evaluada.json")
    modos = parser.add_mutually_exclusive_group()
    modos.add_argument("--enviar-ros", action="store_true", help="Cada clic valido envia XYZ al ESP32")
    modos.add_argument("--rostros", action="store_true", help="Acciona la puerta al detectar un rostro a 0.50 m")
    parser.add_argument("--puerto", default="COM3")
    args = parser.parse_args()
    if (args.enviar_ros or args.rostros) and args.modo != "experimental":
        parser.error("La seleccion XYZ requiere el modo experimental con origen depth")
    try:
        matriz = None
        if args.modo == "experimental":
            datos = json.loads(args.calibracion.read_text(encoding="utf-8"))
            matriz = np.asarray(datos["proyeccion_depth_a_rgb"], dtype=float)
            if matriz.shape != (3, 4) or not np.isfinite(matriz).all() or np.linalg.matrix_rank(matriz) != 3:
                raise ValueError("La matriz de proyección debe ser finita, de rango 3 y tamaño 3x4")
        ejecutar(args, matriz)
    except (OSError, RuntimeError, ValueError, KeyError, cv2.error) as error:
        print(f"Error del visor: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
