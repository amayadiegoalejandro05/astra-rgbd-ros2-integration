"""Detección frontal y disparo por distancia para la puerta simulada."""

from pathlib import Path

import cv2


class DetectorFrontal:
    def __init__(self):
        ruta = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        # Python abre rutas Unicode de Windows, incluso si OpenCV no las admite.
        xml = cv2.FileStorage(ruta.read_text(encoding="utf-8"),
                              cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
        self.modelo = cv2.CascadeClassifier()
        try:
            self.modelo.read(xml.getFirstTopLevelNode())
        finally:
            xml.release()
        if self.modelo.empty():
            raise RuntimeError("OpenCV no pudo cargar el detector frontal de rostros")

    def detectar(self, rgb):
        gris = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
        pequeno = cv2.resize(gris, (320, 240), interpolation=cv2.INTER_AREA)
        rostros = self.modelo.detectMultiScale(
            cv2.equalizeHist(pequeno), scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
        # Usar el rostro de mayor área y recuperar las coordenadas RGB originales.
        if len(rostros):
            return tuple(2 * int(i) for i in max(rostros, key=lambda r: r[2] * r[3]))
        return None


class DisparoPuerta:
    def __init__(self):
        self.armado = True
        self.cercanos = 0
        self.despejado_desde = None

    def observar(self, rostro, z, ahora, disponible):
        # Una pérdida de profundidad con el rostro visible no rearma el sistema.
        despejado = not rostro or (z is not None and z >= 0.60)
        if not self.armado:
            if disponible and despejado:
                if self.despejado_desde is None:
                    self.despejado_desde = ahora
                if ahora - self.despejado_desde >= 0.8:
                    self.armado = True
            else:
                self.despejado_desde = None
            return False
        self.cercanos = self.cercanos + 1 if disponible and z is not None and z <= 0.50 else 0
        return self.cercanos >= 3

    def disparado(self):
        self.armado = False
        self.cercanos = 0
        self.despejado_desde = None
