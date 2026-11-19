"""Guarda una pareja RGB/profundidad y una superposición para auditar el registro."""

import argparse
from contextlib import contextmanager
import ctypes as c
from functools import partial
import json
from pathlib import Path
import sys

import cv2
import numpy as np

from probar_profundidad import cargar_api, configurar_registro, flujo_profundidad, leer_fotograma
from emitir_xyz import xyz_optico


def intrinsecos_depth(api, flujo):
    # Rayos normalizados del conversor OpenNI sobre los ejes de la imagen.
    x0, y0, _ = xyz_optico(api, flujo, 0, 0, 1000)
    x1, y1, _ = xyz_optico(api, flujo, 639, 479, 1000)
    fx, fy = 639 / (x1 - x0), 479 / (y1 - y0)
    return [fx, fy, -x0 * fx, -y0 * fy]


def copiar_profundidad(frame):
    # Copiar antes de liberar el fotograma nativo. Preservar los ceros y el paso de fila.
    if (frame.width, frame.height) != (640, 480) or frame.croppingEnabled:
        raise RuntimeError("Se requiere profundidad 640×480 sin recorte")
    if frame.videoMode.pixelFormat != 100:
        raise RuntimeError("Se requiere profundidad en unidades de 1 mm")
    longitud = (frame.height - 1) * frame.stride + 2 * frame.width
    if not frame.data or frame.stride < 2 * frame.width or frame.dataSize < longitud:
        raise RuntimeError("Búfer de profundidad incompleto")
    datos = c.string_at(frame.data, longitud)
    return np.ndarray((frame.height, frame.width), dtype="<u2", buffer=datos,
                      strides=(frame.stride, 2)).copy()


@contextmanager
def abrir_parejas(api, indice, registrar):
    rgb = cv2.VideoCapture(indice, cv2.CAP_DSHOW)
    try:
        if not rgb.isOpened():
            raise RuntimeError(f"No se pudo abrir RGB en el índice {indice}")
        rgb.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        rgb.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        preparar = partial(configurar_registro, registrar=registrar)
        with flujo_profundidad(api, preparar) as flujo:
            yield rgb, flujo
    finally:
        rgb.release()


def leer_pareja(api, rgb, flujo):
    ok, imagen = rgb.read()
    if not ok or imagen.shape != (480, 640, 3):
        raise RuntimeError("No llegó RGB a 640×480; no se aplicará un reescalado")
    with leer_fotograma(api, flujo) as frame:
        return imagen, copiar_profundidad(frame)


def capturar_pareja(api, indice, registrar):
    with abrir_parejas(api, indice, registrar) as (rgb, flujo):
        # Dar tiempo a la autoexposición. La escena debe permanecer inmóvil.
        for _ in range(20):
            imagen, depth = leer_pareja(api, rgb, flujo)
        intrinsecos = None if registrar else intrinsecos_depth(api, flujo)
    if not np.any(depth):
        raise RuntimeError("El fotograma depth no contiene muestras válidas")
    return imagen, depth, intrinsecos


def dibujar_superposicion(rgb, depth):
    # Destacar discontinuidades de al menos 60 mm entre dos muestras válidas.
    validos = depth > 0
    z = depth.astype(np.int32)
    bordes = np.zeros(depth.shape, dtype=bool)
    bordes[:, 1:] |= validos[:, 1:] & validos[:, :-1] & (abs(z[:, 1:] - z[:, :-1]) >= 60)
    bordes[1:, :] |= validos[1:, :] & validos[:-1, :] & (abs(z[1:, :] - z[:-1, :]) >= 60)
    overlay = rgb.copy()
    overlay[bordes] = (0, 255, 255)
    return overlay


def visualizar_depth(depth):
    # Contraste solo para inspección visual. El PNG métrico se conserva aparte.
    puntos = depth[depth > 0]
    if puntos.size == 0:
        return np.zeros(depth.shape, dtype=np.uint8)
    cerca, lejos = np.percentile(puntos, [5, 95])
    imagen = 255 - np.clip((depth.astype(np.float32) - cerca) * 255 / max(lejos - cerca, 1),
                          0, 255).astype(np.uint8)
    imagen[depth == 0] = 0
    return imagen


def guardar_png(ruta, imagen):
    ok, codificada = cv2.imencode(".png", imagen)
    if not ok:
        raise RuntimeError(f"No se pudo codificar {ruta.name}")
    ruta.write_bytes(codificada.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--rgb-index", type=int, default=1)
    parser.add_argument("--invertir-rgb", action="store_true",
                        help="Voltear horizontalmente el RGB de la comparación principal")
    parser.add_argument("--depth-crudo", action="store_true",
                        help="Capturar con el registro depth a RGB desactivado")
    parser.add_argument("--salida", type=Path, required=True,
                        help="Carpeta nueva para la pareja y sus metadatos")
    args = parser.parse_args()
    if args.rgb_index < 0 or args.salida.exists():
        parser.error("Usa un índice RGB no negativo y una carpeta de salida nueva")
    try:
        rgb, depth, intrinsecos = capturar_pareja(
            cargar_api(args.sdk.resolve()), args.rgb_index, not args.depth_crudo)
        rgb_corregido = cv2.flip(rgb, 1) if args.invertir_rgb else rgb
        args.salida.mkdir(parents=True)
        guardar_png(args.salida / "rgb_original.png", rgb)
        guardar_png(args.salida / "rgb.png", rgb_corregido)
        guardar_png(args.salida / "depth_mm.png", depth)
        guardar_png(args.salida / "depth_vista.png", visualizar_depth(depth))
        guardar_png(args.salida / "superposicion.png", dibujar_superposicion(rgb_corregido, depth))
        guardar_png(args.salida / "superposicion_otra_orientacion.png",
                    dibujar_superposicion(cv2.flip(rgb_corregido, 1), depth))
        (args.salida / "captura.json").write_text(json.dumps({
            "rgb_index": args.rgb_index,
            "rgb_invertido_horizontalmente": args.invertir_rgb,
            "registro_nativo_activado": not args.depth_crudo,
            "intrinsecos_depth_fx_fy_cx_cy": intrinsecos,
            "pixeles_depth_validos": int(np.count_nonzero(depth)),
            "z_centro_mm": int(depth[240, 320]),
        }, indent=2), encoding="utf-8")
    except (OSError, RuntimeError, cv2.error) as error:
        print(f"Error de diagnóstico RGB/depth: {error}", file=sys.stderr)
        return 1
    print(args.salida.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
