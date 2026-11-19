"""Suscriptor de ROS 2 que entrega puntos de la Astra al ESP32 por COM de Windows."""

import argparse
from contextlib import contextmanager
from math import isfinite
from pathlib import Path
import subprocess
import sys
import time

from geometry_msgs.msg import PointStamped
import rclpy
from rclpy.node import Node


def punto_reciente(mensaje, ahora_ns):
    sello = mensaje.header.stamp
    edad = ahora_ns - (sello.sec * 10**9 + sello.nanosec)
    p = mensaje.point
    if (
        mensaje.header.frame_id == "astra_depth_optical_frame"
        and abs(edad) <= 10**9
        and all(map(isfinite, (p.x, p.y, p.z)))
        and p.z > 0
    ):
        return p.x, p.y, p.z
    return None


class Puente(Node):
    def __init__(self, serial, rostro=False):
        super().__init__("esp32_bridge")
        self.serial = serial
        self.id = 0
        self.sello_esperado = None
        self.comando = "F" if rostro else "P"
        # Mientras el ESP32 completa un ciclo, DDS conserva solo la muestra más nueva.
        self.suscripcion = self.create_subscription(PointStamped, "/astra/xyz", self.recibir, 1)
        self.get_logger().info("ESP32 listo. Escuchando /astra/xyz")

    def recibir(self, mensaje):
        sello = mensaje.header.stamp
        if self.sello_esperado is not None and sello.sec * 10**9 + sello.nanosec != self.sello_esperado:
            return
        punto = punto_reciente(mensaje, time.time_ns())
        if punto is None:
            return
        self.id = self.id % 0xFFFFFFFF + 1
        x, y, z = punto
        self.serial.stdin.write(f"{self.comando} {self.id} {x:.7g} {y:.7g} {z:.7g}\n")
        self.serial.stdin.flush()
        # El ayudante valida ACK y DONE para la misma secuencia. Jamás reenvía un ciclo.
        if self.serial.stdout.readline().strip() != f"DONE {self.id}":
            raise RuntimeError(f"Se perdió la confirmación de la secuencia {self.id}")
        self.get_logger().info(f"DONE {self.id} · XYZ = ({x:.4f}, {y:.4f}, {z:.4f}) m")


@contextmanager
def abrir_serial(puerto, rostro=False):
    helper = Path(__file__).resolve().parents[1] / "windows" / "serial_esp32.ps1"
    ruta_windows = subprocess.check_output(["wslpath", "-w", str(helper)], text=True).strip()
    protocolo = "ASTRA2" if rostro else "ASTRA1"
    comando = [
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", ruta_windows, "-Puerto", puerto, "-Protocolo", protocolo,
    ]
    with subprocess.Popen(comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          encoding="ascii") as serial:
        try:
            if serial.stdout.readline().strip() != f"READY {protocolo}":
                raise RuntimeError(f"El ESP32 no confirmó el protocolo {protocolo}")
            yield serial
        finally:
            try:
                serial.stdin.close()
            except BrokenPipeError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puerto", default="COM3")
    parser.add_argument("--ciclos", type=int, help="Finalizar después de este número de ciclos confirmados")
    args = parser.parse_args()
    if args.ciclos is not None and args.ciclos < 1:
        parser.error("--ciclos debe ser mayor que cero")
    with abrir_serial(args.puerto) as serial:
        try:
            rclpy.init()
            nodo = Puente(serial)
            try:
                while rclpy.ok() and (args.ciclos is None or nodo.id < args.ciclos):
                    rclpy.spin_once(nodo)
            finally:
                nodo.destroy_node()
                rclpy.try_shutdown()
        except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
            pass


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error del puente ESP32: {error}", file=sys.stderr)
        sys.exit(1)
