"""Recibe las muestras locales de Windows y publica /astra/xyz en ROS 2."""

import json
from math import isfinite
import sys
import time

from geometry_msgs.msg import PointStamped
import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions


def construir_mensaje(linea):
    datos = json.loads(linea)
    if not isinstance(datos, dict):
        raise ValueError("Se esperaba un objeto JSON")
    sello_ns, xyz = datos.get("stamp_ns"), datos.get("xyz")
    if type(sello_ns) is not int or not 0 < sello_ns < 2**31 * 10**9:
        raise ValueError("Sello de tiempo fuera del intervalo de builtin_interfaces/Time")
    if (
        not isinstance(xyz, list) or len(xyz) != 3
        or not all(type(valor) in (int, float) and isfinite(valor) for valor in xyz)
        or xyz[2] <= 0
    ):
        raise ValueError("Se esperaba un punto XYZ finito con Z positiva")

    # El sello corresponde a la recepción del fotograma en Windows.
    mensaje = PointStamped()
    mensaje.header.stamp.sec, mensaje.header.stamp.nanosec = divmod(sello_ns, 10**9)
    mensaje.header.frame_id = "astra_depth_optical_frame"
    mensaje.point.x, mensaje.point.y, mensaje.point.z = map(float, xyz)
    return mensaje


def main():
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    nodo = Node("astra_xyz")
    try:
        publicador = nodo.create_publisher(PointStamped, "/astra/xyz", 10)
        nodo.get_logger().info("Esperando puntos desde Windows por stdin")
        # El proceso de captura cierra el canal al terminar. No se reenvían muestras viejas.
        for linea in sys.stdin:
            try:
                mensaje = construir_mensaje(linea)
            except (ValueError, OverflowError) as error:
                nodo.get_logger().warning(f"Muestra descartada: {error}", throttle_duration_sec=2)
                continue
            sello = mensaje.header.stamp
            edad_ns = time.time_ns() - (sello.sec * 10**9 + sello.nanosec)
            if not -10**9 <= edad_ns <= 10**9:
                nodo.get_logger().warning(
                    "Muestra fuera de la ventana temporal de 1 s", throttle_duration_sec=2)
                continue
            publicador.publish(mensaje)
    except KeyboardInterrupt:
        pass
    finally:
        nodo.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
