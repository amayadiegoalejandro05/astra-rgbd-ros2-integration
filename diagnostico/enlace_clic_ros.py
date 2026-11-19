"""Canal local del visor de Windows a los nodos ROS 2 en WSL."""

from contextlib import contextmanager
import json
from queue import Empty, SimpleQueue
import re
import subprocess
from threading import Thread
import time


class EnlaceClic:
    def __init__(self, proceso, registro, rostro=False):
        self.proceso = proceso
        self.registro = registro
        self.eventos = SimpleQueue()
        self.listo = False
        self.pendiente = None
        self.estado = "Conectando con ROS 2 y ESP32..."
        self.mensaje_listo = ("Listo. Acerca un rostro a 0.50 m." if rostro
                              else "Listo. Clic en un punto con profundidad.")
        self.hilo = Thread(target=self.leer, daemon=True)
        self.hilo.start()

    def leer(self):
        for linea in self.proceso.stdout:
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            if isinstance(evento, dict) and "tipo" in evento:
                self.registro.write(json.dumps(evento) + "\n")
                self.registro.flush()
                self.eventos.put(evento)
        self.eventos.put({"tipo": "cerrado"})

    def actualizar(self):
        while True:
            try:
                evento = self.eventos.get_nowait()
            except Empty:
                break
            tipo = evento["tipo"]
            if tipo == "listo":
                self.listo = True
                self.estado = self.mensaje_listo
            elif tipo == "confirmado":
                self.pendiente = None
                self.estado = f"ESP32 confirmo el ciclo {evento['secuencia']}."
            elif tipo == "error":
                self.pendiente = None
                self.listo = False
                self.estado = evento["detalle"]
            elif tipo == "cerrado":
                if self.listo or self.pendiente is not None:
                    self.estado = "Enlace cerrado. Abre de nuevo el visor."
                self.pendiente = None
                self.listo = False
        if self.pendiente is not None and time.monotonic() - self.pendiente > 7:
            self.pendiente = None
            self.listo = False
            self.estado = "Sin confirmacion. Abre de nuevo el visor."

    def enviar(self, xyz, sello_ns):
        if not self.listo or self.pendiente is not None:
            return False
        try:
            self.proceso.stdin.write(json.dumps({"stamp_ns": sello_ns, "xyz": xyz}) + "\n")
            self.proceso.stdin.flush()
        except OSError:
            self.listo = False
            self.estado = "Se perdio el enlace con ROS 2."
            return False
        self.estado = "Punto enviado. Esperando confirmacion del ESP32..."
        self.pendiente = time.monotonic()
        return True


@contextmanager
def abrir_enlace(raiz, puerto, rostro=False):
    if not re.fullmatch(r"COM[1-9][0-9]*", puerto):
        raise ValueError("Usa un puerto de Windows como COM3")
    carpeta = raiz / "resultados" / "visor"
    carpeta.mkdir(parents=True, exist_ok=True)
    guion = "source /opt/ros/jazzy/setup.bash && exec python3 -B ros2/clic_xyz.py --puerto " + puerto
    if rostro:
        guion += " --rostros"
    comando = ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc", guion]
    with (carpeta / ("rostros_ros.jsonl" if rostro else "clics_ros.jsonl")).open("a", encoding="utf-8") as registro:
        with subprocess.Popen(comando, cwd=raiz, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              encoding="utf-8", errors="replace") as proceso:
            enlace = EnlaceClic(proceso, registro, rostro)
            try:
                yield enlace
            finally:
                try:
                    proceso.stdin.close()
                except OSError:
                    pass
                try:
                    proceso.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proceso.kill()
                    proceso.wait()
                enlace.hilo.join()
