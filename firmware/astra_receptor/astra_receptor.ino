#include <Arduino.h>
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef SERVO_GPIO
#define SERVO_GPIO 18
#endif

// PWM de 50 Hz para el MG995. Ajustar los pulsos tras observar los topes reales.
constexpr uint32_t SERVO_HZ = 50;
constexpr uint8_t PWM_BITS = 14;
constexpr uint32_t PULSO_0_US = 1000;
constexpr uint32_t PULSO_90_US = 1500;
constexpr uint32_t PAUSA_MS = 700;
constexpr uint32_t PUERTA_ABIERTA_MS = 3000;

enum class Estado { Listo, En90, En0 };
Estado estado = Estado::Listo;
uint32_t secuenciaActiva = 0;
uint32_t desde = 0;
uint32_t esperaMs = PAUSA_MS;
bool pwmDisponible = false;

char linea[112];
size_t usados = 0;
bool descartarLinea = false;

void servo(uint32_t microsegundos) {
  const uint32_t niveles = (1UL << PWM_BITS) - 1;
  ledcWrite(SERVO_GPIO, (microsegundos * niveles + 10000) / 20000);
}

void responder(const char* estadoTexto, uint32_t secuencia) {
  Serial.printf("%s %lu\n", estadoTexto, static_cast<unsigned long>(secuencia));
}

void procesar(char* mensaje) {
  if (strcmp(mensaje, "HELLO ASTRA1") == 0) {
    Serial.println(pwmDisponible ? "READY ASTRA1" : "ERR PWM");
    return;
  }
  if (strcmp(mensaje, "HELLO ASTRA2") == 0) {
    Serial.println(pwmDisponible ? "READY ASTRA2" : "ERR PWM");
    return;
  }

  // Validar el mensaje completo antes de modificar el servo.
  char* resto = nullptr;
  char* tipo = strtok_r(mensaje, " ", &resto);
  char* id = strtok_r(nullptr, " ", &resto);
  if (tipo == nullptr || (strcmp(tipo, "P") != 0 && strcmp(tipo, "F") != 0) || id == nullptr ||
      id[strspn(id, "0123456789")] != '\0') {
    Serial.println("ERR FORMAT");
    return;
  }
  errno = 0;
  unsigned long secuencia = strtoul(id, nullptr, 10);
  if (errno == ERANGE || secuencia == 0 || secuencia > UINT32_MAX) {
    Serial.println("ERR FORMAT");
    return;
  }
  float xyz[3];
  for (float& valor : xyz) {
    char* campo = strtok_r(nullptr, " ", &resto);
    if (campo == nullptr) {
      Serial.println("ERR FORMAT");
      return;
    }
    char* fin = nullptr;
    errno = 0;
    valor = strtof(campo, &fin);
    if (errno == ERANGE || fin == campo || *fin != '\0' || !isfinite(valor)) {
      Serial.println("ERR FORMAT");
      return;
    }
  }
  if (xyz[2] <= 0 || strtok_r(nullptr, " ", &resto) != nullptr) {
    Serial.println("ERR FORMAT");
    return;
  }
  if (!pwmDisponible) {
    Serial.println("ERR PWM");
    return;
  }
  if (estado != Estado::Listo) {
    responder("BUSY", secuencia);
    return;
  }

  secuenciaActiva = secuencia;
  esperaMs = strcmp(tipo, "F") == 0 ? PUERTA_ABIERTA_MS : PAUSA_MS;
  servo(PULSO_90_US);
  desde = millis();
  estado = Estado::En90;
  responder("ACK", secuenciaActiva);
}

void leerSerial() {
  // Limitar el trabajo por vuelta para que el temporizador del servo siga avanzando.
  for (int i = 0; i < 128 && Serial.available(); ++i) {
    int byte = Serial.read();
    if (byte == '\n') {
      if (descartarLinea) {
        Serial.println("ERR FORMAT");
      } else {
        linea[usados] = '\0';
        procesar(linea);
      }
      usados = 0;
      descartarLinea = false;
    } else if (byte != '\r' && !descartarLinea) {
      if (byte < 32 || byte > 126 || usados == sizeof(linea) - 1) {
        descartarLinea = true;
      } else {
        linea[usados++] = static_cast<char>(byte);
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  pwmDisponible = ledcAttach(SERVO_GPIO, SERVO_HZ, PWM_BITS);
  if (pwmDisponible) {
    servo(PULSO_0_US);
  }
}

void loop() {
  // La resta unsigned conserva la comparación cuando millis() desborda.
  if (estado != Estado::Listo && millis() - desde >= esperaMs) {
    if (estado == Estado::En90) {
      servo(PULSO_0_US);
      desde = millis();
      esperaMs = PAUSA_MS;
      estado = Estado::En0;
    } else {
      estado = Estado::Listo;
      responder("DONE", secuenciaActiva);
    }
  }
  leerSerial();
}
