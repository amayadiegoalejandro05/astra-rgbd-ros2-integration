"""Publica una muestra por clic y devuelve la confirmación al visor."""

import argparse
import json
import sys
import time

import rclpy

from astra_xyz import construir_mensaje, PointStamped
from esp32_bridge import abrir_serial, Puente, punto_reciente


def evento(tipo, **datos):
    print(json.dumps({"tipo": tipo, **datos}, ensure_ascii=True), flush=True)


def ejecutar(puerto, rostro=False):
    with abrir_serial(puerto, rostro) as serial:
        rclpy.init()
        puente = Puente(serial, rostro)
        camara = rclpy.create_node("astra_xyz")
        try:
            publicador = camara.create_publisher(PointStamped, "/astra/xyz", 10)
            limite = time.monotonic() + 3
            while not publicador.get_subscription_count() and time.monotonic() < limite:
                time.sleep(0.02)
            if not publicador.get_subscription_count():
                raise RuntimeError("No hay suscriptor para /astra/xyz")
            evento("listo")
            for linea in sys.stdin:
                punto = construir_mensaje(linea)
                if punto_reciente(punto, time.time_ns()) is None:
                    evento("error", detalle="La muestra llego fuera de tiempo.")
                    continue
                sello = punto.header.stamp
                puente.sello_esperado = sello.sec * 10**9 + sello.nanosec
                anterior = puente.id
                inicio = time.monotonic()
                publicador.publish(punto)
                limite = inicio + 1
                while puente.id == anterior and time.monotonic() < limite:
                    rclpy.spin_once(puente, timeout_sec=0.05)
                if puente.id == anterior:
                    raise RuntimeError("El puente no recibio el punto a tiempo.")
                evento("confirmado", secuencia=puente.id,
                       xyz=[punto.point.x, punto.point.y, punto.point.z],
                       latencia_ms=round((time.monotonic() - inicio) * 1000))
        finally:
            camara.destroy_node()
            puente.destroy_node()
            rclpy.try_shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puerto", default="COM3")
    parser.add_argument("--rostros", action="store_true")
    args = parser.parse_args()
    try:
        ejecutar(args.puerto, args.rostros)
    except (OSError, RuntimeError, ValueError) as error:
        evento("error", detalle=str(error))
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
