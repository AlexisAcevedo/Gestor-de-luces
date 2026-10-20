# Protocolo WiZ UDP Local y Especificación de Streaming

[English](wiz_protocol.md) | [Español](wiz_protocol.es.md)

Este documento proporciona la especificación técnica del protocolo de comunicación en red de área local (LAN) de los focos inteligentes Philips WiZ, detallando la estructura de datagramas, los esquemas JSON-RPC, el enrutamiento de descubrimiento en Windows y el comportamiento en streaming de alta frecuencia.

---

## 1. Visión General del Protocolo de Red

Los focos Philips WiZ se comunican en la red local mediante sockets estándar del Protocolo de Datagramas de Usuario (UDP), sin cifrado de transporte, sin protocolos de autenticación y sin intervención de servidores en la nube.

- Puerto UDP por Defecto: `38899` (tanto para destino como origen).
- Formato de Carga Útil: Cadenas JSON codificadas en UTF-8.
- Capa de Transporte: Datagramas UDP sobre IPv4.
- Latencia Típica: Entre 2 ms y 15 ms en redes Wi-Fi locales estándar 802.11 b/g/n de 2.4 GHz.

```
+---------------+                              +---------------+
| Computadora   |                              | Foco WiZ      |
| (192.168.X.A) |                              | (192.168.X.B) |
+-------+-------+                              +-------+-------+
        |                                              |
        | Datagrama UDP -> Puerto 38899                |
        | {"method": "getPilot", "params": {}}         |
        |--------------------------------------------->|
        |                                              |
        | Respuesta UDP <- Puerto 38899                |
        | {"method": "getPilot", "result": {...}}      |
        |<---------------------------------------------|
```

---

## 2. Descubrimiento de Focos y Travesía de Firewall en Windows

Los dispositivos WiZ admiten descubrimiento automático en la subred local. No obstante, en sistemas Windows con múltiples interfaces de red se presentan particularidades de enrutamiento y filtrado de firewall.

### Broadcast Dirigido de Subred vs. Broadcast Global

Emitir paquetes de descubrimiento a `255.255.255.255` suele fallar en equipos Windows donde existen adaptadores de red virtuales activos (como WSL, Hyper-V, VMware o adaptadores virtuales de Docker). Windows puede enrutar el paquete `255.255.255.255` hacia una placa virtual en lugar de la interfaz física conectada al router.

**Implementación en `gestor_luces.cli`**:
1. Inspección de Ruta de Socket: Se abre un socket UDP ficticio hacia una dirección externa (`8.8.8.8:80`) para detectar qué dirección IPv4 física selecciona la tabla de enrutamiento del sistema operativo.
2. Cálculo de Broadcast Dirigido: Se calcula la dirección de difusión de la subred `/24` (por ejemplo, `192.168.100.255`) y se transmite el paquete de descubrimiento directamente a dicha dirección.

### Mecanismo de Apertura de Firewall por Unicast Directo

Cuando la PC envía un paquete de broadcast UDP, los focos responden con paquetes UDP unicast dirigidos a la IP de la computadora. En diversas configuraciones de Windows Defender Firewall, estos paquetes entrantes no solicitados son descartados silenciosamente por considerarse tráfico no confiable.

**Sondeo por Unicast Directo (`probe_single_ip`)**:
Si el descubrimiento por broadcast no recibe respuestas, `gestor_luces` envía un datagrama unicast directo (`getSystemConfig`) a la dirección `192.168.X.Y:38899`. Al ser un paquete saliente originado en la PC, el firewall de Windows abre de forma automática un paso de retorno (*hole punching* por inspección de estado), permitiendo que la respuesta del foco ingrese sin necesidad de alterar las reglas globales del firewall.

---

## 3. Métodos y Esquemas del Protocolo JSON-RPC

### 3.1 `getPilot` (Consulta de Estado en Tiempo Real)

Permite obtener el estado operativo actual del foco, su nivel de brillo, color y escena activa.

**Petición:**
```json
{
  "method": "getPilot",
  "params": {}
}
```

**Respuesta:**
```json
{
  "method": "getPilot",
  "env": "pro",
  "result": {
    "mac": "cc40850a02d4",
    "rssi": -58,
    "src": "udp",
    "state": true,
    "sceneId": 0,
    "speed": 100,
    "dimming": 85,
    "temp": 4200,
    "r": 255,
    "g": 140,
    "b": 20,
    "c": 0,
    "w": 0
  }
}
```

**Descripción de Campos del Resultado:**
- `mac`: Dirección MAC física del foco (sin dos puntos).
- `rssi`: Nivel de señal Wi-Fi recibida en dBm.
- `state`: Booleano (`true` = encendido, `false` = apagado).
- `dimming`: Porcentaje de brillo de `10` a `100`.
- `temp`: Temperatura de color en Kelvin (`2200` a `6500`).
- `r`, `g`, `b`: Intensidad de los canales RGB (`0` a `255`). Presente cuando opera en modo color.
- `c`, `w`: Niveles PWM para los canales de blanco frío (*cool white*) y cálido (*warm white*).
- `sceneId`: Identificador numérico de la escena activa (`0` indica modo manual estático de color o temperatura).
- `speed`: Multiplicador de velocidad para escenas animadas (`20` a `200`).

---

### 3.2 `setPilot` (Control de Estado y Parámetros)

Ordena al foco modificar su estado de energía, brillo, color, temperatura o escena.

**Parámetros:**
- `state` *(booleano, opcional)*: Encendido (`true` o `false`).
- `dimming` *(entero, opcional)*: Porcentaje de brillo entre `10` y `100`.
- `temp` *(entero, opcional)*: Temperatura Kelvin entre `2200` y `6500`. Excluyente con `r`, `g`, `b` y `sceneId`.
- `r`, `g`, `b` *(enteros, opcional)*: Valores rojo, verde y azul entre `0` y `255`.
- `sceneId` *(entero, opcional)*: Número de escena nativa (`1` a `36`).
- `speed` *(entero, opcional)*: Multiplicador de velocidad de animación (`20` a `200`).

#### Ejemplos de Comandos:

1. **Apagar el foco:**
   ```json
   {"method": "setPilot", "params": {"state": false}}
   ```

2. **Establecer Color Naranja Atardecer al 100% de Brillo:**
   ```json
   {
     "method": "setPilot",
     "params": {
       "state": true,
       "dimming": 100,
       "r": 255,
       "g": 120,
       "b": 10
     }
   }
   ```

3. **Establecer Blanco Cálido (2700K) al 60% de Brillo:**
   ```json
   {
     "method": "setPilot",
     "params": {
       "state": true,
       "dimming": 60,
       "temp": 2700
     }
   }
   ```

4. **Activar Escena "Fireplace" (ID 5) al 150% de Velocidad:**
   ```json
   {
     "method": "setPilot",
     "params": {
       "state": true,
       "sceneId": 5,
       "speed": 150,
       "dimming": 80
     }
   }
   ```

**Respuesta de Confirmación:**
```json
{
  "method": "setPilot",
  "env": "pro",
  "result": {
    "success": true
  }
}
```

---

### 3.3 `getSystemConfig` (Metadatos de Hardware y Firmware)

Consulta el modelo de hardware, tipo de módulo y versión de firmware.

**Petición:**
```json
{
  "method": "getSystemConfig",
  "params": {}
}
```

**Respuesta:**
```json
{
  "method": "getSystemConfig",
  "env": "pro",
  "result": {
    "mac": "cc40850a02d4",
    "homeId": 123456,
    "roomId": 1,
    "moduleName": "ESP01_SHRGB1C_31",
    "fwVersion": "1.30.0",
    "groupId": 0,
    "typeId": 0
  }
}
```

---

## 4. Streaming Continuo de Alta Frecuencia (`stream_pilot`)

La iluminación dinámica en tiempo real (como el modo Ambilight de pantalla o el modo Música por WASAPI) requiere transmitir actualizaciones de color sucesivas a frecuencias elevadas.

### Arquitectura sin Espera de Confirmación (Fire-and-Forget)

Los comandos RPC tradicionales esperan la respuesta de confirmación del foco:

$$\text{Petición} \longrightarrow \text{Procesamiento en Foco} \longrightarrow \text{Respuesta ACK}$$

En un bucle interactivo de streaming, esperar el ACK de cada paquete introduce una variabilidad de latencia (*jitter*) de entre 10 ms y 30 ms. Si un paquete se retrasa en la red, todo el hilo de procesamiento se congela.

`WizUdpController.stream_pilot` prescinde por completo de la espera de confirmación:
1. Construye el datagrama JSON mínimo indispensable (`state`, `r`, `g`, `b`, `dimming`).
2. Despacha el paquete directamente al socket UDP.
3. Retorna el control de ejecución inmediatamente sin bloquearse en `sock.recvfrom()`.

### Restricción de Frecuencia por Hardware (Límite de 10 Hz)

Los microcontroladores integrados en los focos WiZ (generalmente Espressif ESP8266 o ESP32) disponen de un búfer de recepción en anillo de capacidad reducida.

- Transmitir a tasas superiores a 15 Hz satura rápidamente dicho búfer.
- El desbordamiento dispara el temporizador guardián (*watchdog timer*) del microcontrolador, provocando un reinicio del foco con parpadeo blanco y desconexión momentánea de la red Wi-Fi.
- Por esta razón, `StreamRateLimiter` impone un intervalo mínimo de **100 milisegundos (10 Hz)** por cada IP de foco.

---

## 5. Catálogo de Escenas Nativas del Firmware

La siguiente tabla lista las 36 escenas de fábrica incluidas en el firmware de los focos WiZ, con su identificador, nombre, categoría y soporte de velocidad variable:

| ID | Nombre | Categoría | Admite Velocidad | Descripción |
|---|---|---|---|---|
| 1 | Ocean | Naturaleza | Sí | Olas suaves de azules acuáticos y cian |
| 2 | Romance | Ambiente | Sí | Tonos tenues de magenta, violeta y rosa |
| 3 | Sunset | Naturaleza | Sí | Ámbar cálido, dorados y rojizos de atardecer |
| 4 | Party | Dinámica | Sí | Rotación multicolor de alta energía |
| 5 | Fireplace | Ambiente | Sí | Simulación de brasas con oscilaciones rojizas y ámbar |
| 6 | Cozy | Ambiente | Sí | Brillo cálido y confortable de interiores |
| 7 | Forest | Naturaleza | Sí | Gama relajante de verdes profundos y oliva |
| 8 | Pastel colors | Dinámica | Sí | Ciclo suave de tonos pasteles desaturados |
| 9 | Wake-up | Ambiente | Sí | Progresión matinal gradual de luz día |
| 10 | Bedtime | Ambiente | Sí | Desvanecimiento tenue y cálido para dormir |
| 11 | Warm white | Blanco | No | Blanco cálido estático a 2700K |
| 12 | Daylight | Blanco | No | Blanco neutro estático a 4200K |
| 13 | Cool white | Blanco | No | Blanco frío brillante estático a 6500K |
| 14 | Night light | Blanco | No | Luz de noche de muy baja intensidad en 2200K |
| 15 | Focus | Blanco | No | Luz día intensa a 5000K para concentración |
| 16 | Relax | Blanco | No | Blanco suave y relajante a 2500K |
| 17 | True colors | Blanco | No | Blanco de alto índice de reproducción cromática (CRI) |
| 18 | TV time | Blanco | No | Iluminación de fondo tenue para pantallas |
| 19 | Plantgrowth | Naturaleza | No | Espectro específico para crecimiento vegetal |
| 20 | Spring | Naturaleza | Sí | Verdes frescos y amarillos florales |
| 21 | Summer | Naturaleza | Sí | Tonos diurnos brillantes y cielo despejado |
| 22 | Fall | Naturaleza | Sí | Rojos otoñales, ocres y anaranjados |
| 23 | Deep dive | Naturaleza | Sí | Azules oceánicos profundos e índigo |
| 24 | Jungle | Naturaleza | Sí | Verdes selváticos tropicales |
| 25 | Mojito | Dinámica | Sí | Pulsos frescos de verde lima y amarillo |
| 26 | Club | Dinámica | Sí | Destellos saturados de club nocturno |
| 27 | Christmas | Festiva | Sí | Alternancia de verde navideño y rojo festivo |
| 28 | Halloween | Festiva | Sí | Destellos ámbar, naranja y violeta |
| 29 | Candlelight | Ambiente | Sí | Simulación delicada de la llama de una vela |
| 30 | Golden white | Blanco | No | Blanco dorado cálido a 2400K |
| 31 | Pulse | Dinámica | Sí | Pulsos rítmicos de brillo y color |
| 32 | Steampunk | Dinámica | Sí | Bronce antiguo, cobre y ámbar cálido |
| 33 | Diwali | Festiva | Sí | Paleta cálida y colorida de festival de luces |
| 34 | White | Blanco | No | Blanco puro equilibrado |
| 35 | Alarm | Dinámica | Sí | Señal de alerta con destellos intermitentes |
| 36 | Snowy sky | Naturaleza | Sí | Azul invernal pálido y blancos nítidos |

