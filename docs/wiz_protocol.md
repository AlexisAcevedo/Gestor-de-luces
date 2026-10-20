# WiZ Local UDP Protocol & Streaming Specification

[English](wiz_protocol.md) | [Español](wiz_protocol.es.md)

This document provides a technical specification of the WiZ local area network (LAN) communication protocol, detailing datagram structures, JSON-RPC schemas, discovery routing mechanics, and continuous high-frequency streaming behaviors.

---

## 1. Network Protocol Overview

Philips WiZ smart bulbs communicate over local networks using standard User Datagram Protocol (UDP) sockets without transport encryption, authentication handshakes, or cloud verification.

- Default UDP Port: `38899` (both destination and source).
- Payload Format: UTF-8 encoded JSON strings.
- Transport Layer: IPv4 UDP datagrams.
- Typical Latency: 2 ms to 15 ms across a standard 802.11 b/g/n 2.4 GHz local Wi-Fi network.

```
+---------------+                              +---------------+
| Host Computer |                              | WiZ Bulb      |
| (192.168.X.A) |                              | (192.168.X.B) |
+-------+-------+                              +-------+-------+
        |                                              |
        | UDP Datagram -> Port 38899                   |
        | {"method": "getPilot", "params": {}}         |
        |--------------------------------------------->|
        |                                              |
        | UDP Response <- Port 38899                   |
        | {"method": "getPilot", "result": {...}}      |
        |<---------------------------------------------|
```

---

## 2. Bulb Discovery & Firewall Traversal

WiZ devices support automatic discovery on local subnets. However, Windows operating systems with multiple network interfaces introduce specific routing and firewall complications.

### Directed Subnet Broadcast vs. Global Broadcast

Sending a discovery broadcast to `255.255.255.255` frequently fails on Windows workstations where virtual adapters (such as WSL, Hyper-V, VMware, or Docker vEthernet) are active. Windows may route `255.255.255.255` out of a virtual adapter rather than the physical Ethernet or Wi-Fi interface connected to the router.

**Implementation in `gestor_luces.cli`**:
1. Socket Route Inspection: Open a dummy UDP socket to an external address (`8.8.8.8:80`) to discover the active physical IPv4 address selected by the Windows routing table.
2. Directed Subnet Computation: Compute the directed `/24` subnet broadcast address (e.g., `192.168.100.255`) and transmit discovery packets directly to that destination.

### The Windows Firewall Unicast Hole-Punching Fallback

When a PC transmits a UDP broadcast packet, bulbs reply with unicast UDP packets addressed directly to the PC's IP. On many Windows configurations, the Windows Defender Firewall classifies these unsolicited incoming UDP packets as untrusted and drops them silently.

**Direct Unicast Probing (`probe_single_ip`)**:
When broadcast discovery fails or when scanning a known IP address, `gestor_luces` issues a direct unicast UDP datagram (`getSystemConfig`) to `192.168.X.Y:38899`. Because Windows recognizes the outbound datagram, it automatically opens a temporary stateful inspection pinhole, allowing the bulb's reply to pass through the firewall without requiring manual inbound firewall rule adjustments.

---

## 3. JSON-RPC Protocol Methods & Schemas

### 3.1 `getPilot` (Query Real-Time State)

Used to inspect the bulb's operational parameters, power status, current color, and active scene.

**Request:**
```json
{
  "method": "getPilot",
  "params": {}
}
```

**Response:**
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

**Result Field Descriptions:**
- `mac`: Physical hardware MAC address of the bulb (without colons).
- `rssi`: Received Signal Strength Indicator in dBm.
- `state`: Boolean (`true` = on, `false` = off).
- `dimming`: Integer percentage from `10` to `100`.
- `temp`: Color temperature in degrees Kelvin (`2200` to `6500`).
- `r`, `g`, `b`: RGB channel levels (`0` to `255`). Present when operating in RGB mode.
- `c`, `w`: Cool white and warm white PWM channel levels.
- `sceneId`: Integer ID of the active native scene (`0` indicates manual static color or temperature mode).
- `speed`: Playback speed percentage for animated scenes (`20` to `200`).

---

### 3.2 `setPilot` (Control State and Parameters)

Commands the bulb to alter its power state, brightness, color, temperature, or scene.

**Parameters:**
- `state` *(boolean, optional)*: Power state (`true` or `false`).
- `dimming` *(integer, optional)*: Brightness level between `10` and `100`.
- `temp` *(integer, optional)*: Color temperature in Kelvin between `2200` and `6500`. Mutually exclusive with `r`, `g`, `b` and `sceneId`.
- `r`, `g`, `b` *(integers, optional)*: Red, green, and blue levels between `0` and `255`.
- `sceneId` *(integer, optional)*: Built-in scene identifier (`1` to `36`).
- `speed` *(integer, optional)*: Animation speed multiplier (`20` to `200`).

#### Command Examples:

1. **Power Off:**
   ```json
   {"method": "setPilot", "params": {"state": false}}
   ```

2. **Set Color (Orange Sunset) at 100% Brightness:**
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

3. **Set Warm White (2700K) at 60% Brightness:**
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

4. **Activate "Fireplace" Scene (ID 5) with 150% Animation Speed:**
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

**Response:**
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

### 3.3 `getSystemConfig` (Hardware & Firmware Metadata)

Queries hardware model, module type, and firmware revision.

**Request:**
```json
{
  "method": "getSystemConfig",
  "params": {}
}
```

**Response:**
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

## 4. Continuous High-Frequency Streaming (`stream_pilot`)

Continuous dynamic lighting (such as desktop Ambilight or WASAPI Music Sync) requires sending successive color updates at high frequencies.

### Fire-and-Forget Architecture

Standard RPC commands wait for a bulb acknowledgment response:

$$\text{Request} \longrightarrow \text{Bulb Processing} \longrightarrow \text{ACK Response}$$

In an interactive streaming loop, waiting for an ACK on every frame introduces transmission jitter (10 ms to 30 ms). If a network packet is delayed, the whole pipeline stalls.

`WizUdpController.stream_pilot` bypasses ACK waiting completely:
1. Formats the minimal JSON payload (`state`, `r`, `g`, `b`, `dimming`).
2. Transmits the UDP packet directly onto the network socket.
3. Immediately returns control to the caller without blocking on `sock.recvfrom()`.

### The 10 Hz Rate Limit Constraint

WiZ bulb microcontrollers (typically Espressif ESP8266 or ESP32) maintain a small internal ring buffer for incoming UDP packets. 

- Transmitting at > 15 Hz quickly overruns the microcontroller's socket buffer.
- Buffer overflow triggers the bulb's hardware watchdog timer (WDT), causing the bulb to reboot, flicker white, and temporarily drop off Wi-Fi.
- `StreamRateLimiter` enforces a strict minimum inter-packet interval of **100 milliseconds (10 Hz)** per target bulb IP.

---

## 5. Built-in Scene Catalog Reference

The table below catalogs all 36 native firmware scenes present in Philips WiZ bulbs, indicating their identifier, display name, category, and whether the firmware supports variable speed adjustments (`speed` parameter):

| ID | Scene Name | Category | Supports Speed? | Description |
|---|---|---|---|---|
| 1 | Ocean | Nature | Yes | Gentle aquatic blue and cyan waves |
| 2 | Romance | Ambient | Yes | Soft magenta, violet, and deep rose |
| 3 | Sunset | Nature | Yes | Warm amber, gold, and evening crimson |
| 4 | Party | Dynamic | Yes | High-energy multi-color strobe rotations |
| 5 | Fireplace | Ambient | Yes | Flickering embers with subtle red/orange shifts |
| 6 | Cozy | Ambient | Yes | Warm, comfortable interior glow |
| 7 | Forest | Nature | Yes | Calming shades of deep green and olive |
| 8 | Pastel colors | Dynamic | Yes | Soft desaturated multi-hue cycles |
| 9 | Wake-up | Ambient | Yes | Morning daylight progression |
| 10 | Bedtime | Ambient | Yes | Dim warm fade transition |
| 11 | Warm white | White | No | Static 2700K warm incandescent white |
| 12 | Daylight | White | No | Static 4200K neutral interior daylight |
| 13 | Cool white | White | No | Static 6500K crisp daylight |
| 14 | Night light | White | No | Ultra-low brightness warm amber (2200K) |
| 15 | Focus | White | No | High-intensity 5000K daylight for alertness |
| 16 | Relax | White | No | Low-glare 2500K relaxing ambient white |
| 17 | True colors | White | No | High CRI neutral white |
| 18 | TV time | White | No | Dim background illumination for displays |
| 19 | Plantgrowth | Nature | No | Specialized horticultural spectrum |
| 20 | Spring | Nature | Yes | Fresh greens and delicate flower yellows |
| 21 | Summer | Nature | Yes | Vibrant daylight and warm sky tones |
| 22 | Fall | Nature | Yes | Rich maple reds, ochre, and warm orange |
| 23 | Deep dive | Nature | Yes | Deep oceanic blues and indigos |
| 24 | Jungle | Nature | Yes | Tropical rainforest greens |
| 25 | Mojito | Dynamic | Yes | Crisp lime green and light yellow pulses |
| 26 | Club | Dynamic | Yes | Saturated nightclub club pulses |
| 27 | Christmas | Holiday | Yes | Alternating evergreen and festive red |
| 28 | Halloween | Holiday | Yes | Spooky amber orange and purple flashes |
| 29 | Candlelight | Ambient | Yes | Delicate flame simulation |
| 30 | Golden white | White | No | Warm golden 2400K illumination |
| 31 | Pulse | Dynamic | Yes | Rhythmic brightness and color pulsing |
| 32 | Steampunk | Dynamic | Yes | Antique bronze, copper, and warm amber |
| 33 | Diwali | Holiday | Yes | Festival of lights warm colorful palette |
| 34 | White | White | No | Pure balanced white |
| 35 | Alarm | Dynamic | Yes | Urgent flashing alert signal |
| 36 | Snowy sky | Nature | Yes | Pale winter blue and crisp cool whites |

