/*
 * Diccionario bilingue (Ingles / Espanol neutro profesional) y motor de localizacion DOM.
 *
 * Centraliza todas las cadenas estaticas y dinamicas de la Consola Fotometrica para que
 * el cambio de idioma sea instantaneo sin recargar la ventana ni perder la telemetria en vivo.
 * Por requerimiento de diseno, los nombres de las 36 escenas de firmware de WiZ (Ocean,
 * Sunset, Fireplace, etc.) se conservan en su denominacion original oficial en ambos idiomas.
 */

(function () {
  "use strict";

  const DICTIONARIES = {
    en: {
      /* Titulo del documento y cabecera del riel */
      "app.windowTitle": "WiZ Architectural Lighting Console",
      "rail.ariaLabel": "Lighting fixtures",
      "rail.title": "Photometric Console",
      "rail.subtitle": "Local UDP 38899 Direct Control",
      "rail.langGroupAria": "Interface language",
      "rail.scanBtn": "Scan network",
      "rail.scanningBtn": "Scanning...",
      "rail.addByIpBtn": "Add by IP",
      "rail.selectAll": "Select all fixtures",
      "rail.onlineCount": "{online} / {total} online",
      "rail.onlineZero": "0 online",
      "rail.fixtureListAria": "Registered fixtures",
      "rail.emptyTitle": "No WiZ fixtures registered yet.",
      "rail.emptySubtitle": "Use Scan network or Add by IP to connect.",
      "rail.selectFixtureAria": "Select {name}",
      "rail.statusOnline": "Online",
      "rail.statusOffline": "Offline",
      "rail.renameBtn": "Rename",
      "rail.renameAria": "Rename {name}",
      "rail.powerOn": "ON",
      "rail.powerOff": "OFF",
      "rail.powerToggleOnAria": "Turn off {name}",
      "rail.powerToggleOffAria": "Turn on {name}",
      "rail.syncNowBtn": "Sync now",
      "rail.syncNowTitle": "Query getPilot state from all bulbs",
      "rail.autoSync": "Auto-sync (3s)",
      "rail.statusReady": "Ready for local UDP telemetry.",

      /* Cabecera del escenario fotometrico */
      "stage.ariaLabel": "Light parameter controls",
      "stage.noFixture": "No fixture selected",
      "stage.controllingOne": "Controlling 1 fixture: {name}",
      "stage.controllingMany": "Controlling {count} fixtures ({name} primary)",
      "stage.stateOffline": "OFFLINE",
      "stage.stateOff": "OFF",
      "stage.stateOffStandby": "OFF · Standby ({brightness}%)",
      "stage.stateOnRgb": "ON · RGB ({r}, {g}, {b}) · {brightness}%",
      "stage.stateOnScene": "ON · Scene: {scene} · {brightness}%",
      "stage.stateOnKelvin": "ON · {kelvin} K · {brightness}%",
      "stage.saveStateBtn": "Save current state",
      "stage.saveStateTitle": "Save current bulb state as a custom preset",
      "stage.turnOn": "Turn ON",
      "stage.turnOff": "Turn OFF",

      /* Temporizador de apagado (Sleep Timer) */
      "sleep.title": "Sleep Timer (Progressive Fade)",
      "sleep.description": "Gradually dims fixtures during the final 30% of the countdown before powering off.",
      "sleep.badgeInactive": "Timer inactive",
      "sleep.badgeActive": "Sleep timer: {countdown} remaining · {phase}",
      "sleep.phaseFade": "Progressive fade active",
      "sleep.phaseSteady": "Steady countdown",
      "sleep.quickPresetsAria": "Sleep timer quick durations",
      "sleep.durationLabel": "Timer duration in minutes (1 to 240)",
      "sleep.customMinutesAria": "Custom sleep timer minutes",
      "sleep.startBtn": "Start Timer",
      "sleep.cancelBtn": "Cancel Timer",
      "sleep.cancelBtnActive": "Cancel ({countdown})",

      /* Atenuacion maestra (Dimming) */
      "dimming.title": "Luminous Flux (Dimming)",
      "dimming.sliderAria": "Master brightness percentage",
      "dimming.presetsAria": "Quick dimming presets",

      /* Pestanas de modo */
      "tabs.ariaLabel": "Lighting emission mode",
      "tabs.rgb": "Chromatic (RGB)",
      "tabs.temperature": "White (Kelvin)",
      "tabs.scene": "WiZ Scenes (36)",
      "tabs.custom": "Custom Presets",
      "tabs.customWithCount": "Presets ({count})",
      "tabs.ambilight": "Ambilight",
      "tabs.music": "Music Sync",

      /* Panel 1: RGB */
      "rgb.wheelAria": "Interactive HSV color wheel",
      "rgb.redLabel": "Red (0-255)",
      "rgb.greenLabel": "Green (0-255)",
      "rgb.blueLabel": "Blue (0-255)",
      "rgb.hexLabel": "Hex Code",
      "rgb.applyBtn": "Apply RGB",
      "rgb.swatchesCaption": "Reference Chromatic Swatches",
      "rgb.swatchesAria": "Curated RGB swatches",
      "rgb.swatchSodium": "Sodium Amber",
      "rgb.swatchCrimson": "Crimson Laser",
      "rgb.swatchUltraviolet": "Ultraviolet",
      "rgb.swatchCerulean": "Cerulean Sky",
      "rgb.swatchMint": "Phosphor Mint",
      "rgb.swatchHalogen": "Halogen Gold",

      /* Panel 2: Temperatura Kelvin */
      "kelvin.title": "Correlated Color Temperature (CCT)",
      "kelvin.description": "Continuous blackbody locus from 2200 K warm filament to 6500 K overcast daylight.",
      "kelvin.sliderAria": "Color temperature in Kelvin",
      "kelvin.scaleWarm": "2200 K Warm Amber",
      "kelvin.scaleNeutral": "4200 K Neutral",
      "kelvin.scaleCool": "6500 K Cool Daylight",
      "kelvin.presetsAria": "Architectural white presets",
      "kelvin.preset2200": "Candlelight",
      "kelvin.preset2700": "Warm White",
      "kelvin.preset3500": "Neutral Halogen",
      "kelvin.preset4200": "Daylight",
      "kelvin.preset5000": "Studio Gallery",
      "kelvin.preset6500": "Cool Daylight",

      /* Panel 3: Escenas nativas WiZ (36) */
      "scenes.filterAria": "Filter scenes by category",
      "scenes.catFavorites": "Favorites",
      "scenes.catFavoritesCount": "Favorites ({count})",
      "scenes.catAll": "All (36)",
      "scenes.catAllCount": "All ({count})",
      "scenes.catWhite": "White",
      "scenes.catWhiteCount": "White ({count})",
      "scenes.catAmbient": "Ambient",
      "scenes.catAmbientCount": "Ambient ({count})",
      "scenes.catNature": "Nature",
      "scenes.catNatureCount": "Nature ({count})",
      "scenes.catDynamic": "Dynamic",
      "scenes.catDynamicCount": "Dynamic ({count})",
      "scenes.catHoliday": "Holiday",
      "scenes.catHolidayCount": "Holiday ({count})",
      "scenes.speedLabel": "Transition Speed",
      "scenes.gridAria": "WiZ firmware scenes",
      "scenes.tagDynamic": "Dynamic",
      "scenes.tagStatic": "Static",
      "scenes.badgeActive": "ACTIVE",
      "scenes.favAddAria": "Pin {name} to favorites",
      "scenes.favRemoveAria": "Unpin {name} from favorites",
      "scenes.emptyFavorites": "No favorite scenes pinned yet. Click the star icon on any scene to pin it.",
      "scenes.plantGrowth": "Plant growth",

      /* Panel 4: Presets personalizados */
      "custom.title": "Saved Custom Presets",
      "custom.description": "Capture any RGB color, Kelvin temperature, or dynamic scene with brightness into local JSON storage.",
      "custom.gridAria": "Saved custom lighting presets",
      "custom.emptyTitle": "No custom presets saved yet.",
      "custom.emptySubtitle": "Configure any color, Kelvin temperature, or scene and click Save current state.",
      "custom.applyAria": "Apply preset {name}",
      "custom.summaryScene": "Scene: {scene} · {brightness}%",
      "custom.favoriteRemoveTitle": "Remove from system tray Favorite presets",
      "custom.favoriteAddTitle": "Add to system tray Favorite presets",
      "custom.favoritedBtn": "Favorited",
      "custom.favoriteBtn": "Favorite",
      "custom.applyBtn": "Apply",
      "custom.editBtn": "Edit",
      "custom.deleteBtn": "Delete",

      /* Panel 5: Ambilight */
      "ambi.statusStandby": "STANDBY",
      "ambi.statusStreaming": "STREAMING 10 HZ",
      "ambi.statusLive": "LIVE",
      "ambi.framesSent": "{count} frames sent",
      "ambi.telemetryFpsFrames": "{fps} FPS · {count} frames",
      "ambi.swatchTitle": "Sampled Screen Chromaticity",
      "ambi.startBtn": "Start Ambilight",
      "ambi.stopBtn": "Stop Ambilight",
      "ambi.sourceLabel": "Source Display",
      "ambi.modeLabel": "Color Extraction Mode",
      "ambi.modeVibrant": "Vibrant / Dominant",
      "ambi.modeAverage": "Average Screen Color",
      "ambi.smoothingLabel": "EMA Smoothing Response (Alpha)",
      "ambi.scaleCinematic": "0.15 Cinematic",
      "ambi.scaleBalanced": "0.38 Balanced",
      "ambi.scaleFast": "0.75 Fast Response",
      "ambi.autoBrightness": "Track screen brightness automatically (ITU-R BT.709 luminance)",
      "ambi.minBrightnessLabel": "Min Brightness Floor",
      "ambi.minBrightnessHint": "Prevents dark movie scenes from dimming the fixture below this threshold.",

      /* Panel 6: Music Sync */
      "music.statusStandby": "STANDBY",
      "music.statusActive": "WASAPI 10.5 HZ",
      "music.statusLive": "LIVE",
      "music.framesSent": "{count} frames sent",
      "music.telemetryFpsFrames": "{fps} FPS · {count} frames",
      "music.swatchTitle": "Acoustic Spectrum Output",
      "music.metersAria": "Real-time FFT frequency band meters",
      "music.bassLabel": "Bass (20-250 Hz)",
      "music.midLabel": "Mid (250-2k Hz)",
      "music.trebleLabel": "Treble (2k-12k Hz)",
      "music.rmsLabel": "RMS Volume",
      "music.startBtn": "Start Music Sync",
      "music.stopBtn": "Stop Music Sync",
      "music.deviceLabel": "Loopback Audio Device",
      "music.paletteLabel": "Color Palette",
      "music.paletteSpectrum": "Spectrum (Bass/Mid/Treble)",
      "music.paletteClub": "Club Pulse (Warm/Neon)",
      "music.paletteChill": "Aurora Chill (Ocean/Teal)",
      "music.sensitivityLabel": "Beat Sensitivity",
      "music.scaleSubtle": "0.4x Subtle",
      "music.scaleBalanced": "1.0x Balanced",
      "music.scaleHighGain": "2.5x High Gain",
      "music.smoothingLabel": "EMA Smoothing Response (Alpha)",
      "music.scaleSmooth": "0.20 Smooth",
      "music.scalePunchy": "0.50 Punchy",
      "music.scaleInstant": "0.85 Instant Beat",
      "music.audioBrightness": "Modulate brightness with audio volume",

      /* Dialogos modales */
      "dialog.cancel": "Cancel",
      "dialog.addTitle": "Register Fixture by IPv4",
      "dialog.addSubtitle": "Directly probe a WiZ bulb on UDP port 38899 when broadcast discovery is filtered.",
      "dialog.addIpLabel": "Fixture IPv4 Address",
      "dialog.addNameLabel": "Fixture Label (Optional)",
      "dialog.addNamePlaceholder": "Studio Key Light",
      "dialog.addSubmit": "Probe and Register",

      "dialog.renameTitle": "Rename Fixture",
      "dialog.renameIpDisplay": "Fixture IP: {ip} ({mac})",
      "dialog.renameNameLabel": "New Fixture Name",
      "dialog.renameSubmit": "Save Name",

      "dialog.presetSaveTitle": "Save Custom Preset",
      "dialog.presetSaveSubtitle": "Snapshots the active fixture state into local persistent storage.",
      "dialog.presetEditTitle": "Edit Custom Preset",
      "dialog.presetEditSubtitle": "Rename this preset or overwrite its parameters with the current fixture state.",
      "dialog.presetNameLabel": "Preset Label",
      "dialog.presetNamePlaceholder": "Late Night Coding",
      "dialog.presetOverwrite": "Overwrite preset parameters with current live bulb state",
      "dialog.presetSaveSubmit": "Save Preset",
      "dialog.presetUpdateSubmit": "Update Preset",

      /* Mensajes de estado (Status Banner) */
      "status.warning": "Warning: {error}",
      "status.commError": "Communication error: {error}",
      "status.connected": "Connected to local UDP lighting service.",
      "status.scanDone": "Network scan completed.",
      "status.registeredIp": "Registered fixture at {ip}.",
      "status.renamedBulb": "Renamed {ip} to \"{name}\".",
      "status.selectionUpdated": "Updated target selection.",
      "status.multiSelectionUpdated": "Updated multi-fixture selection.",
      "status.syncedLive": "Synchronized live state from UDP getPilot.",
      "status.syncedTray": "Synchronized state from system tray.",
      "status.autoSyncStep": "Auto-synced live bulb telemetry.",
      "status.autoSyncEnabled": "Auto-sync enabled (polling UDP getPilot every 3s).",
      "status.autoSyncPaused": "Auto-sync paused.",
      "status.bulbTurnedOn": "{name} turned ON.",
      "status.bulbTurnedOff": "{name} turned OFF.",
      "status.masterTurnedOn": "Master power turned ON.",
      "status.masterTurnedOff": "Master power turned OFF.",
      "status.brightnessSet": "Set brightness to {brightness}%.",
      "status.rgbApplied": "Applied RGB ({r}, {g}, {b}).",
      "status.swatchApplied": "Applied swatch RGB ({r}, {g}, {b}).",
      "status.kelvinSet": "Set white balance to {kelvin} K.",
      "status.sceneActivated": "Activated scene #{id}: {name}.",
      "status.sceneSpeedUpdated": "Updated scene #{id} speed to {speed}.",
      "status.sleepStarted": "Sleep timer started for {minutes} min with progressive fade.",
      "status.sleepCancelled": "Sleep timer cancelled.",
      "status.presetSaved": "Saved custom preset \"{name}\".",
      "status.presetUpdated": "Updated custom preset \"{name}\".",
      "status.presetApplied": "Applied custom preset \"{name}\".",
      "status.presetDeleted": "Deleted preset \"{name}\".",
      "status.favoriteAdded": "Added \"{name}\" to tray favorite presets.",
      "status.favoriteRemoved": "Removed \"{name}\" from tray favorite presets.",
      "status.ambiStarted": "Ambilight screen sync active (10 Hz).",
      "status.ambiStopped": "Ambilight screen sync stopped.",
      "status.ambiDisplaySwitched": "Ambilight switched to Display {display}.",
      "status.ambiModeChanged": "Ambilight extraction mode set to {mode}.",
      "status.ambiSmoothingChanged": "Ambilight EMA smoothing set to {alpha}.",
      "status.ambiAutoBriOn": "Ambilight automatic screen luminance enabled.",
      "status.ambiAutoBriOff": "Ambilight using manual brightness ceiling.",
      "status.ambiMinBriChanged": "Ambilight minimum brightness floor set to {floor}%.",
      "status.sceneFavAdded": "Pinned scene \"{name}\" to favorites.",
      "status.sceneFavRemoved": "Unpinned scene \"{name}\" from favorites.",
      "status.musicStarted": "Music sync active (WASAPI Loopback 10.5 Hz).",
      "status.musicStopped": "Music sync stopped.",
      "status.musicDeviceSwitched": "Switched WASAPI loopback audio device.",
      "status.musicPaletteChanged": "Music palette set to {palette}.",
      "status.musicSensitivityChanged": "Beat sensitivity set to {sensitivity}x.",
      "status.musicSmoothingChanged": "Music EMA smoothing set to {alpha}.",
      "status.musicAudioBriOn": "Dynamic beat brightness modulation enabled.",
      "status.musicAudioBriOff": "Music sync using fixed brightness ceiling.",
      "status.languageChanged": "Interface language changed to English."
    },

    es: {
      /* Titulo del documento y cabecera del riel */
      "app.windowTitle": "Consola de Iluminación Arquitectónica WiZ",
      "rail.ariaLabel": "Luminarias registradas",
      "rail.title": "Consola Fotométrica",
      "rail.subtitle": "Control Directo UDP Local 38899",
      "rail.langGroupAria": "Idioma de la interfaz",
      "rail.scanBtn": "Escanear red",
      "rail.scanningBtn": "Escaneando...",
      "rail.addByIpBtn": "Agregar por IP",
      "rail.selectAll": "Seleccionar todas",
      "rail.onlineCount": "{online} / {total} en línea",
      "rail.onlineZero": "0 en línea",
      "rail.fixtureListAria": "Luminarias registradas",
      "rail.emptyTitle": "Aún no hay luminarias WiZ registradas.",
      "rail.emptySubtitle": "Usa Escanear red o Agregar por IP para conectar.",
      "rail.selectFixtureAria": "Seleccionar {name}",
      "rail.statusOnline": "En línea",
      "rail.statusOffline": "Sin conexión",
      "rail.renameBtn": "Renombrar",
      "rail.renameAria": "Renombrar {name}",
      "rail.powerOn": "ENC",
      "rail.powerOff": "APA",
      "rail.powerToggleOnAria": "Apagar {name}",
      "rail.powerToggleOffAria": "Encender {name}",
      "rail.syncNowBtn": "Sincronizar",
      "rail.syncNowTitle": "Consultar el estado getPilot de todas las luminarias",
      "rail.autoSync": "Auto-sinc (3s)",
      "rail.statusReady": "Listo para telemetría UDP local.",

      /* Cabecera del escenario fotometrico */
      "stage.ariaLabel": "Controles de parámetros lumínicos",
      "stage.noFixture": "Ninguna luminaria seleccionada",
      "stage.controllingOne": "Controlando 1 luminaria: {name}",
      "stage.controllingMany": "Controlando {count} luminarias ({name} principal)",
      "stage.stateOffline": "SIN CONEXIÓN",
      "stage.stateOff": "APAGADO",
      "stage.stateOffStandby": "APAGADO · En espera ({brightness}%)",
      "stage.stateOnRgb": "ENCENDIDO · RGB ({r}, {g}, {b}) · {brightness}%",
      "stage.stateOnScene": "ENCENDIDO · Escena: {scene} · {brightness}%",
      "stage.stateOnKelvin": "ENCENDIDO · {kelvin} K · {brightness}%",
      "stage.saveStateBtn": "Guardar estado actual",
      "stage.saveStateTitle": "Guardar el estado actual de la luminaria como escena personalizada",
      "stage.turnOn": "Encender",
      "stage.turnOff": "Apagar",

      /* Temporizador de apagado (Sleep Timer) */
      "sleep.title": "Temporizador de Apagado (Atenuación Progresiva)",
      "sleep.description": "Atenúa gradualmente las luminarias durante el último 30% de la cuenta regresiva antes de apagarlas.",
      "sleep.badgeInactive": "Temporizador inactivo",
      "sleep.badgeActive": "Temporizador: {countdown} restantes · {phase}",
      "sleep.phaseFade": "Atenuación progresiva activa",
      "sleep.phaseSteady": "Cuenta regresiva estable",
      "sleep.quickPresetsAria": "Duraciones rápidas del temporizador",
      "sleep.durationLabel": "Duración del temporizador en minutos (1 a 240)",
      "sleep.customMinutesAria": "Minutos personalizados del temporizador",
      "sleep.startBtn": "Iniciar",
      "sleep.cancelBtn": "Cancelar",
      "sleep.cancelBtnActive": "Cancelar ({countdown})",

      /* Atenuacion maestra (Dimming) */
      "dimming.title": "Flujo Luminoso (Brillo)",
      "dimming.sliderAria": "Porcentaje de brillo maestro",
      "dimming.presetsAria": "Niveles rápidos de brillo",

      /* Pestanas de modo */
      "tabs.ariaLabel": "Modo de emisión lumínica",
      "tabs.rgb": "Cromático (RGB)",
      "tabs.temperature": "Blanco (Kelvin)",
      "tabs.scene": "Escenas WiZ (36)",
      "tabs.custom": "Presets Guardados",
      "tabs.customWithCount": "Presets ({count})",
      "tabs.ambilight": "Ambilight",
      "tabs.music": "Sincro Musical",

      /* Panel 1: RGB */
      "rgb.wheelAria": "Rueda de color HSV interactiva",
      "rgb.redLabel": "Rojo (0-255)",
      "rgb.greenLabel": "Verde (0-255)",
      "rgb.blueLabel": "Azul (0-255)",
      "rgb.hexLabel": "Código Hex",
      "rgb.applyBtn": "Aplicar RGB",
      "rgb.swatchesCaption": "Muestras Cromáticas de Referencia",
      "rgb.swatchesAria": "Muestras RGB seleccionadas",
      "rgb.swatchSodium": "Ámbar Sodio",
      "rgb.swatchCrimson": "Láser Carmesí",
      "rgb.swatchUltraviolet": "Ultravioleta",
      "rgb.swatchCerulean": "Cielo Cerúleo",
      "rgb.swatchMint": "Menta Fósforo",
      "rgb.swatchHalogen": "Oro Halógeno",

      /* Panel 2: Temperatura Kelvin */
      "kelvin.title": "Temperatura de Color Correlacionada (CCT)",
      "kelvin.description": "Curva continua de cuerpo negro desde 2200 K filamento cálido hasta 6500 K luz de día fría.",
      "kelvin.sliderAria": "Temperatura de color en grados Kelvin",
      "kelvin.scaleWarm": "2200 K Ámbar Cálido",
      "kelvin.scaleNeutral": "4200 K Neutro",
      "kelvin.scaleCool": "6500 K Luz de Día Fría",
      "kelvin.presetsAria": "Ajustes rápidos de blanco arquitectónico",
      "kelvin.preset2200": "Luz de Vela",
      "kelvin.preset2700": "Blanco Cálido",
      "kelvin.preset3500": "Halógeno Neutro",
      "kelvin.preset4200": "Luz de Día",
      "kelvin.preset5000": "Galería de Estudio",
      "kelvin.preset6500": "Luz Fría",

      /* Panel 3: Escenas nativas WiZ (36) */
      "scenes.filterAria": "Filtrar escenas por categoría",
      "scenes.catFavorites": "Favoritas",
      "scenes.catFavoritesCount": "Favoritas ({count})",
      "scenes.catAll": "Todas (36)",
      "scenes.catAllCount": "Todas ({count})",
      "scenes.catWhite": "Blancos",
      "scenes.catWhiteCount": "Blancos ({count})",
      "scenes.catAmbient": "Ambiente",
      "scenes.catAmbientCount": "Ambiente ({count})",
      "scenes.catNature": "Naturaleza",
      "scenes.catNatureCount": "Naturaleza ({count})",
      "scenes.catDynamic": "Dinámicas",
      "scenes.catDynamicCount": "Dinámicas ({count})",
      "scenes.catHoliday": "Festivas",
      "scenes.catHolidayCount": "Festivas ({count})",
      "scenes.speedLabel": "Velocidad de Transición",
      "scenes.gridAria": "Escenas de firmware WiZ",
      "scenes.tagDynamic": "Dinámica",
      "scenes.tagStatic": "Estática",
      "scenes.badgeActive": "ACTIVA",
      "scenes.favAddAria": "Fijar {name} en favoritas",
      "scenes.favRemoveAria": "Quitar {name} de favoritas",
      "scenes.emptyFavorites": "Aún no hay escenas favoritas fijadas. Haz clic en el icono de estrella de cualquier escena para fijarla.",
      "scenes.plantGrowth": "Crecimiento de plantas",

      /* Panel 4: Presets personalizados */
      "custom.title": "Escenas Personalizadas Guardadas",
      "custom.description": "Captura cualquier color RGB, temperatura Kelvin o escena dinámica con su brillo en almacenamiento JSON local.",
      "custom.gridAria": "Escenas personalizadas guardadas",
      "custom.emptyTitle": "Aún no hay escenas personalizadas guardadas.",
      "custom.emptySubtitle": "Configura cualquier color, temperatura Kelvin o escena y haz clic en Guardar estado actual.",
      "custom.applyAria": "Aplicar escena {name}",
      "custom.summaryScene": "Escena: {scene} · {brightness}%",
      "custom.favoriteRemoveTitle": "Quitar de Escenas favoritas en la bandeja del sistema",
      "custom.favoriteAddTitle": "Agregar a Escenas favoritas en la bandeja del sistema",
      "custom.favoritedBtn": "En favoritos",
      "custom.favoriteBtn": "Favorita",
      "custom.applyBtn": "Aplicar",
      "custom.editBtn": "Editar",
      "custom.deleteBtn": "Eliminar",

      /* Panel 5: Ambilight */
      "ambi.statusStandby": "EN ESPERA",
      "ambi.statusStreaming": "TRANSMITIENDO 10 HZ",
      "ambi.statusLive": "EN VIVO",
      "ambi.framesSent": "{count} fotogramas enviados",
      "ambi.telemetryFpsFrames": "{fps} FPS · {count} fotogramas",
      "ambi.swatchTitle": "Cromaticidad Muestreada en Pantalla",
      "ambi.startBtn": "Iniciar Ambilight",
      "ambi.stopBtn": "Detener Ambilight",
      "ambi.sourceLabel": "Pantalla de Origen",
      "ambi.modeLabel": "Modo de Extracción de Color",
      "ambi.modeVibrant": "Vibrante / Dominante",
      "ambi.modeAverage": "Color Promedio de Pantalla",
      "ambi.smoothingLabel": "Respuesta de Suavizado EMA (Alfa)",
      "ambi.scaleCinematic": "0.15 Cinematográfico",
      "ambi.scaleBalanced": "0.38 Equilibrado",
      "ambi.scaleFast": "0.75 Respuesta Rápida",
      "ambi.autoBrightness": "Ajustar el brillo automáticamente según la luminancia de pantalla (ITU-R BT.709)",
      "ambi.minBrightnessLabel": "Piso Mínimo de Brillo",
      "ambi.minBrightnessHint": "Evita que escenas oscuras atenúen la luminaria por debajo de este umbral.",

      /* Panel 6: Music Sync */
      "music.statusStandby": "EN ESPERA",
      "music.statusActive": "WASAPI 10.5 HZ",
      "music.statusLive": "EN VIVO",
      "music.framesSent": "{count} fotogramas enviados",
      "music.telemetryFpsFrames": "{fps} FPS · {count} fotogramas",
      "music.swatchTitle": "Salida Espectral Acústica",
      "music.metersAria": "Medidores de bandas de frecuencia FFT en tiempo real",
      "music.bassLabel": "Graves (20-250 Hz)",
      "music.midLabel": "Medios (250-2k Hz)",
      "music.trebleLabel": "Agudos (2k-12k Hz)",
      "music.rmsLabel": "Volumen RMS",
      "music.startBtn": "Iniciar Sincronización Musical",
      "music.stopBtn": "Detener Sincronización Musical",
      "music.deviceLabel": "Dispositivo de Audio Loopback",
      "music.paletteLabel": "Paleta de Color",
      "music.paletteSpectrum": "Espectro (Graves/Medios/Agudos)",
      "music.paletteClub": "Pulso Club (Cálido/Neón)",
      "music.paletteChill": "Aurora Chill (Océano/Turquesa)",
      "music.sensitivityLabel": "Sensibilidad al Ritmo",
      "music.scaleSubtle": "0.4x Sutil",
      "music.scaleBalanced": "1.0x Equilibrado",
      "music.scaleHighGain": "2.5x Alta Ganancia",
      "music.smoothingLabel": "Respuesta de Suavizado EMA (Alfa)",
      "music.scaleSmooth": "0.20 Suave",
      "music.scalePunchy": "0.50 Dinámico",
      "music.scaleInstant": "0.85 Pulso Instantáneo",
      "music.audioBrightness": "Modular el brillo con el volumen de audio",

      /* Dialogos modales */
      "dialog.cancel": "Cancelar",
      "dialog.addTitle": "Registrar Luminaria por IPv4",
      "dialog.addSubtitle": "Sondea directamente un foco WiZ en el puerto UDP 38899 cuando el descubrimiento por difusión está filtrado.",
      "dialog.addIpLabel": "Dirección IPv4 de la Luminaria",
      "dialog.addNameLabel": "Etiqueta de la Luminaria (Opcional)",
      "dialog.addNamePlaceholder": "Luz Principal de Estudio",
      "dialog.addSubmit": "Sondear y Registrar",

      "dialog.renameTitle": "Renombrar Luminaria",
      "dialog.renameIpDisplay": "IP de la luminaria: {ip} ({mac})",
      "dialog.renameNameLabel": "Nuevo Nombre de la Luminaria",
      "dialog.renameSubmit": "Guardar Nombre",

      "dialog.presetSaveTitle": "Guardar Escena Personalizada",
      "dialog.presetSaveSubtitle": "Captura el estado activo de la luminaria en el almacenamiento local persistente.",
      "dialog.presetEditTitle": "Editar Escena Personalizada",
      "dialog.presetEditSubtitle": "Renombra esta escena o sobrescribe sus parámetros con el estado actual de la luminaria.",
      "dialog.presetNameLabel": "Nombre de la Escena",
      "dialog.presetNamePlaceholder": "Programación Nocturna",
      "dialog.presetOverwrite": "Sobrescribir parámetros con el estado en vivo actual de la luminaria",
      "dialog.presetSaveSubmit": "Guardar Escena",
      "dialog.presetUpdateSubmit": "Actualizar Escena",

      /* Mensajes de estado (Status Banner) */
      "status.warning": "Advertencia: {error}",
      "status.commError": "Error de comunicación: {error}",
      "status.connected": "Conectado al servicio local de iluminación UDP.",
      "status.scanDone": "Escaneo de red completado.",
      "status.registeredIp": "Luminaria registrada en {ip}.",
      "status.renamedBulb": "Luminaria {ip} renombrada a \"{name}\".",
      "status.selectionUpdated": "Selección de luminarias actualizada.",
      "status.multiSelectionUpdated": "Selección múltiple de luminarias actualizada.",
      "status.syncedLive": "Estado en vivo sincronizado mediante UDP getPilot.",
      "status.syncedTray": "Estado sincronizado desde la bandeja del sistema.",
      "status.autoSyncStep": "Telemetría de luminarias sincronizada automáticamente.",
      "status.autoSyncEnabled": "Auto-sincronización activada (sondeo UDP getPilot cada 3s).",
      "status.autoSyncPaused": "Auto-sincronización en pausa.",
      "status.bulbTurnedOn": "{name} encendida.",
      "status.bulbTurnedOff": "{name} apagada.",
      "status.masterTurnedOn": "Alimentación maestra encendida.",
      "status.masterTurnedOff": "Alimentación maestra apagada.",
      "status.brightnessSet": "Brillo ajustado al {brightness}%.",
      "status.rgbApplied": "Color RGB ({r}, {g}, {b}) aplicado.",
      "status.swatchApplied": "Muestra RGB ({r}, {g}, {b}) aplicada.",
      "status.kelvinSet": "Balance de blanco ajustado a {kelvin} K.",
      "status.sceneActivated": "Escena #{id} activada: {name}.",
      "status.sceneSpeedUpdated": "Velocidad de la escena #{id} ajustada a {speed}.",
      "status.sleepStarted": "Temporizador iniciado por {minutes} min con atenuación progresiva.",
      "status.sleepCancelled": "Temporizador de apagado cancelado.",
      "status.presetSaved": "Escena personalizada \"{name}\" guardada.",
      "status.presetUpdated": "Escena personalizada \"{name}\" actualizada.",
      "status.presetApplied": "Escena personalizada \"{name}\" aplicada.",
      "status.presetDeleted": "Escena personalizada \"{name}\" eliminada.",
      "status.favoriteAdded": "\"{name}\" agregada a Escenas favoritas en la bandeja.",
      "status.favoriteRemoved": "\"{name}\" quitada de Escenas favoritas en la bandeja.",
      "status.ambiStarted": "Sincronización de pantalla Ambilight activa (10 Hz).",
      "status.ambiStopped": "Sincronización de pantalla Ambilight detenida.",
      "status.ambiDisplaySwitched": "Ambilight cambiado a la pantalla {display}.",
      "status.ambiModeChanged": "Modo de extracción Ambilight cambiado a {mode}.",
      "status.ambiSmoothingChanged": "Suavizado EMA de Ambilight ajustado a {alpha}.",
      "status.ambiAutoBriOn": "Luminancia automática de pantalla Ambilight activada.",
      "status.ambiAutoBriOff": "Ambilight usando límite de brillo manual.",
      "status.ambiMinBriChanged": "Piso mínimo de brillo Ambilight ajustado al {floor}%.",
      "status.sceneFavAdded": "Escena \"{name}\" fijada en favoritas.",
      "status.sceneFavRemoved": "Escena \"{name}\" quitada de favoritas.",
      "status.musicStarted": "Sincronización musical activa (WASAPI Loopback 10.5 Hz).",
      "status.musicStopped": "Sincronización musical detenida.",
      "status.musicDeviceSwitched": "Dispositivo de audio loopback WASAPI cambiado.",
      "status.musicPaletteChanged": "Paleta musical cambiada a {palette}.",
      "status.musicSensitivityChanged": "Sensibilidad al ritmo ajustada a {sensitivity}x.",
      "status.musicSmoothingChanged": "Suavizado EMA musical ajustado a {alpha}.",
      "status.musicAudioBriOn": "Modulación dinámica de brillo por ritmo activada.",
      "status.musicAudioBriOff": "Sincronización musical usando techo fijo de brillo.",
      "status.languageChanged": "Idioma de la interfaz cambiado a Español."
    }
  };

  let currentLanguage = "en";

  function normalizeLanguage(lang) {
    const cleaned = String(lang || "en").trim().toLowerCase();
    return cleaned === "es" ? "es" : "en";
  }

  function getLanguage() {
    return currentLanguage;
  }

  function setLanguage(lang) {
    currentLanguage = normalizeLanguage(lang);
    if (typeof document !== "undefined" && document.documentElement) {
      document.documentElement.lang = currentLanguage;
    }
    return currentLanguage;
  }

  function t(key, vars) {
    const activeDict = DICTIONARIES[currentLanguage] || DICTIONARIES.en;
    let template = activeDict[key];
    if (template === undefined) {
      template = DICTIONARIES.en[key] !== undefined ? DICTIONARIES.en[key] : key;
    }
    if (!vars || typeof vars !== "object") {
      return template;
    }
    return template.replace(/\{(\w+)\}/g, (match, token) => {
      return Object.prototype.hasOwnProperty.call(vars, token) ? String(vars[token]) : match;
    });
  }

  function translateDom(root) {
    const scope = root || (typeof document !== "undefined" ? document : null);
    if (!scope) return;

    if (typeof document !== "undefined") {
      document.title = t("app.windowTitle");
    }

    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (key) {
        el.textContent = t(key);
      }
    });

    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.getAttribute("data-i18n-title");
      if (key) {
        el.setAttribute("title", t(key));
      }
    });

    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key) {
        el.setAttribute("placeholder", t(key));
      }
    });

    scope.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
      const key = el.getAttribute("data-i18n-aria-label");
      if (key) {
        el.setAttribute("aria-label", t(key));
      }
    });
  }

  window.I18N = {
    dictionaries: DICTIONARIES,
    getLanguage,
    setLanguage,
    t,
    translateDom
  };
})();

