"""Emite puntos XYZ ópticos en metros desde la Astra en Windows."""

import argparse
from contextlib import redirect_stdout
import ctypes as c
import json
from math import isfinite
from pathlib import Path
import subprocess
import sys
import time

from probar_profundidad import (
    cargar_api, configurar_registro, flujo_profundidad, leer_fotograma,
    medir_centro, verificar,
)


def xyz_optico(api, flujo, u, v, z_mm):
    x, y, z = c.c_float(), c.c_float(), c.c_float()
    verificar(api, "Convertir profundidad a 3D", api.oniCoordinateConverterDepthToWorld(
        flujo, u, v, z_mm, c.byref(x), c.byref(y), c.byref(z)))
    # OpenNI usa Y hacia arriba; el marco óptico de ROS usa Y hacia abajo.
    punto = x.value / 1000, -y.value / 1000, z.value / 1000
    if not all(map(isfinite, punto)) or punto[2] <= 0:
        raise RuntimeError("OpenNI devolvió un punto 3D inválido")
    return punto


def emitir(api, muestras, salida):
    # El canal stdout queda reservado para JSON. Los diagnósticos van a stderr.
    with redirect_stdout(sys.stderr), flujo_profundidad(api, configurar_registro) as flujo:
        tomadas = 0
        proxima = 0.0
        while muestras is None or tomadas < muestras:
            with leer_fotograma(api, flujo) as frame:
                ahora = time.monotonic()
                if ahora < proxima:
                    continue
                sello_ns = time.time_ns()
                proxima = ahora + 0.2
                tomadas += 1
                z_mm = medir_centro(frame, informar_modo=tomadas == 1)
                if z_mm == 0:
                    continue
                xyz = xyz_optico(api, flujo, frame.width // 2, frame.height // 2, z_mm)
                print(json.dumps({"stamp_ns": sello_ns, "xyz": xyz}, allow_nan=False),
                      file=salida, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--muestras", type=int, help="Cantidad de intentos de lectura a 5 Hz")
    parser.add_argument("--ros", action="store_true", help="Iniciar el nodo astra_xyz en Ubuntu WSL")
    args = parser.parse_args()
    if args.muestras is not None and args.muestras < 1:
        parser.error("--muestras debe ser mayor que cero")
    try:
        api = cargar_api(args.sdk.resolve())
        if not args.ros:
            emitir(api, args.muestras, sys.stdout)
            return 0

        # Canal directo al nodo. PowerShell queda fuera del transporte de las muestras.
        comando = ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc",
                   "source /opt/ros/jazzy/setup.bash && exec python3 -B ros2/astra_xyz.py"]
        with subprocess.Popen(comando, cwd=Path(__file__).resolve().parents[1],
                              stdin=subprocess.PIPE, encoding="utf-8") as nodo:
            try:
                emitir(api, args.muestras, nodo.stdin)
            finally:
                nodo.stdin.close()
            return nodo.wait()
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
