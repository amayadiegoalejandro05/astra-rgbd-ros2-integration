"""Mide el desplazamiento entre el mismo borde o esquina en RGB y depth."""

import argparse
import json
from math import hypot
from pathlib import Path
from statistics import median

import cv2
import numpy as np


def revisar(carpeta):
    # Ambas vistas tienen el tamaño original para medir en píxeles del sensor.
    rgb = cv2.imdecode(np.frombuffer((carpeta / "rgb.png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    depth = cv2.imdecode(np.frombuffer((carpeta / "depth_vista.png").read_bytes(), np.uint8),
                        cv2.IMREAD_COLOR)
    if rgb is None or depth is None or rgb.shape != depth.shape:
        raise ValueError("Se necesitan las vistas RGB y depth de la misma captura")
    ancho = rgb.shape[1]
    puntos = []
    ventana = "RGB (izquierda) / Depth (derecha)"

    def marcar(evento, x, y, _flags, _param):
        if evento != cv2.EVENT_LBUTTONDOWN:
            return
        # Primero RGB, luego el mismo detalle físico en profundidad.
        if not (0 <= y < rgb.shape[0] and 0 <= x < 2 * ancho):
            return
        if (x < ancho) == (len(puntos) % 2 == 0):
            puntos.append((x, y))

    cv2.namedWindow(ventana, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(ventana, marcar)
    try:
        while True:
            vista = np.hstack((rgb, depth))
            for i, punto in enumerate(puntos):
                cv2.circle(vista, punto, 5, (0, 255, 255), 1)
                cv2.putText(vista, str(i // 2 + 1), (punto[0] + 7, punto[1]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            cv2.imshow(ventana, vista)
            tecla = cv2.waitKey(30) & 0xFF
            if tecla == ord("u") and puntos:
                puntos.pop()
            if tecla == 27 or cv2.getWindowProperty(ventana, cv2.WND_PROP_VISIBLE) < 1:
                return []
            if tecla in (10, 13) and len(puntos) >= 2 and len(puntos) % 2 == 0:
                break
    finally:
        cv2.destroyAllWindows()

    pares = []
    for (u, v), (u_depth_vista, v_depth) in zip(puntos[::2], puntos[1::2]):
        u_depth = u_depth_vista - ancho
        dx, dy = u_depth - u, v_depth - v
        pares.append({"rgb_uv": [u, v], "depth_uv": [u_depth, v_depth],
                      "dx_px": dx, "dy_px": dy, "error_px": hypot(dx, dy)})
    return pares


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captura", type=Path)
    args = parser.parse_args()
    print("Marca RGB y luego depth para cada detalle. U deshace, Enter guarda, Esc cancela.")
    pares = revisar(args.captura)
    if pares:
        errores = [p["error_px"] for p in pares]
        informe = {"pares": pares, "mediana_px": median(errores), "maximo_px": max(errores)}
        destino = args.captura / "error_registro.json"
        with destino.open("x", encoding="utf-8") as archivo:
            json.dump(informe, archivo, indent=2)
        print(f"Mediana: {informe['mediana_px']:.2f} px. Máximo: {informe['maximo_px']:.2f} px. {destino}")


if __name__ == "__main__":
    main()
