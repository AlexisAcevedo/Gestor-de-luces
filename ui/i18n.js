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
      "rail.title": "Lighting Console",
      "rail.subtitle": "Local WiZ Network Control",
      "rail.langGroupAria": "Interface language",
      "theme.switcherAria": "Interface theme",
      "theme.stoneShort": "Light",
      "theme.darkShort": "Dark",
      "theme.stoneTooltip": "Light theme",
      "theme.darkTooltip": "Dark theme",
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
      "rail.renameAria": "Rename {name}",
      "rail.removeAria": "Remove {name}",
      "rail.powerToggleOnAria": "Turn off {name}",
      "rail.powerToggleOffAria": "Turn on {name}",
      "rail.syncNowBtn": "Sync now",
      "rail.syncNowTitle": "Refresh live state from all bulbs",
      "rail.autoSync": "Auto-sync (3s)",
      "rail.statusReady": "Ready for local WiZ control.",
      "rail.openDrawerAria": "Open fixtures and network drawer",
      "rail.closeDrawerAria": "Close fixtures drawer",

      /* Cabecera del escenario fotometrico */
      "stage.ariaLabel": "Light parameter controls",
      "stage.noFixture": "No fixture selected",
      "stage.noneSelected": "No fixtures selected",
      "stage.stateNoneSelected": "No target",
      "stage.emptyNoBulbs": "No WiZ bulbs registered yet. Scan your local network or add one by IP.",
      "stage.emptyNoSelection": "No fixtures are currently selected. Select at least one to control lighting.",
      "stage.stateStreamingAmbi": "Streaming · Ambilight",
      "stage.stateStreamingMusic": "Streaming · Music Sync",
      "stage.controllingMany": "Controlling {count} fixtures ({name} primary)",
      "stage.controllingList": "Controlling {count} fixtures: {names}",
      "stage.stateOffline": "Offline",
      "stage.stateOff": "Off",
      "stage.stateOffStandby": "Off · Standby ({brightness}%)",
      "stage.stateOnRgb": "On · RGB ({r}, {g}, {b}) · {brightness}%",
      "stage.stateOnScene": "On · Scene: {scene} · {brightness}%",
      "stage.stateOnKelvin": "On · {kelvin} K · {brightness}%",
      "stage.saveStateBtn": "Save current state",
      "stage.saveStateTitle": "Save current bulb state as a custom preset",
      "stage.turnOn": "Turn on",
      "stage.turnOff": "Turn off",

      /* Temporizador de apagado (Sleep Timer) */
      "sleep.title": "Sleep timer",
      "sleep.description": "Gradually dims fixtures during the final 30% of the countdown before powering off.",
      "sleep.badgeInactive": "Timer inactive",
      "sleep.badgeActive": "Sleep timer: {countdown} remaining · {phase}",
      "sleep.phaseFade": "Progressive fade active",
      "sleep.phaseSteady": "Steady countdown",
      "sleep.quickPresetsAria": "Sleep timer quick durations",
      "sleep.durationLabel": "Timer duration in minutes (1 to 240)",
      "sleep.customMinutesAria": "Custom sleep timer minutes",
      "sleep.startBtn": "Start timer",
      "sleep.cancelBtn": "Cancel timer",
      "sleep.cancelBtnActive": "Cancel ({countdown})",

      /* Atenuacion maestra (Dimming) */
      "dimming.title": "Brightness",
      "dimming.sliderAria": "Master brightness percentage",
      "dimming.presetsAria": "Quick dimming presets",

      /* Pestanas de modo */
      "tabs.ariaLabel": "Lighting emission mode",
      "tabs.rgb": "Color",
      "tabs.temperature": "White",
      "tabs.scene": "Scenes",
      "tabs.custom": "Presets",
      "tabs.customWithCount": "Presets ({count})",
      "tabs.ambilight": "Ambilight",
      "tabs.music": "Music",

      /* Panel 1: RGB */
      "rgb.wheelAria": "Interactive HSV color wheel",
      "rgb.wheelValueText": "Hue {hue}°, Saturation {saturation}%",
      "rgb.manualCaption": "Precision RGB & hex values",
      "rgb.redLabel": "Red (0-255)",
      "rgb.greenLabel": "Green (0-255)",
      "rgb.blueLabel": "Blue (0-255)",
      "rgb.hexLabel": "Hex code",
      "rgb.applyBtn": "Apply RGB",
      "rgb.swatchesCaption": "Reference chromatic swatches",
      "rgb.swatchesAria": "Curated RGB swatches",
      "rgb.swatchSodium": "Sodium Amber",
      "rgb.swatchCrimson": "Crimson Laser",
      "rgb.swatchUltraviolet": "Ultraviolet",
      "rgb.swatchCerulean": "Cerulean Sky",
      "rgb.swatchMint": "Phosphor Mint",
      "rgb.swatchHalogen": "Halogen Gold",

      /* Panel 2: Temperatura Kelvin */
      "kelvin.title": "Color Temperature",
      "kelvin.description": "Adjust warmth from 2200 K warm candlelight to 6500 K cool daylight.",
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
      "custom.description": "Save any color, white temperature, or scene with its brightness for quick reuse.",
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
      "ambi.statusLive": "LIVE",
      "ambi.telemetryZero": "0 FPS · 0 frames",
      "ambi.telemetryFpsFrames": "{fps} FPS · {count} frames",
      "ambi.swatchTitle": "Detected Screen Color",
      "ambi.startBtn": "Start Ambilight",
      "ambi.stopBtn": "Stop Ambilight",
      "ambi.sourceLabel": "Source Display",
      "ambi.defaultDisplay": "Display 1 (Primary)",
      "ambi.displayItem": "Display {index} ({width}x{height})",
      "ambi.allDisplays": "All displays ({width}x{height})",
      "ambi.modeLabel": "Color Extraction Mode",
      "ambi.modeVibrant": "Vibrant / Dominant",
      "ambi.modeAverage": "Average Screen Color",
      "ambi.smoothingLabel": "Transition Smoothing",
      "ambi.scaleCinematic": "0.15 Cinematic",
      "ambi.scaleBalanced": "0.38 Balanced",
      "ambi.scaleFast": "0.75 Fast Response",
      "ambi.smoothingPresetsAria": "Smoothing presets",
      "ambi.autoBrightness": "Match screen brightness automatically",
      "ambi.minBrightnessLabel": "Min Brightness Floor",
      "ambi.minBrightnessHint": "Prevents dark movie scenes from dimming the fixture below this threshold.",

      /* Panel 6: Music Sync */
      "music.statusStandby": "STANDBY",
      "music.statusLive": "LIVE",
      "music.telemetryZero": "0 FPS · 0 frames",
      "music.telemetryFpsFrames": "{fps} FPS · {count} frames",
      "music.swatchTitle": "Live Audio Color",
      "music.metersAria": "Real-time audio frequency meters",
      "music.bassLabel": "Bass (20-250 Hz)",
      "music.midLabel": "Mid (250-2k Hz)",
      "music.trebleLabel": "Treble (2k-12k Hz)",
      "music.rmsLabel": "Volume Level",
      "music.startBtn": "Start Music Sync",
      "music.stopBtn": "Stop Music Sync",
      "music.deviceLabel": "Audio Output Device",
      "music.defaultDevice": "Default System Output",
      "music.defaultPrefix": "Default",
      "music.paletteLabel": "Color Palette",
      "music.paletteSpectrum": "Spectrum (Bass/Mid/Treble)",
      "music.paletteClub": "Club Pulse (Warm/Neon)",
      "music.paletteChill": "Aurora Chill (Ocean/Teal)",
      "music.sensitivityLabel": "Beat Sensitivity",
      "music.scaleSubtle": "0.4x Subtle",
      "music.scaleBalanced": "1.0x Balanced",
      "music.scaleHighGain": "2.5x High Gain",
      "music.sensitivityPresetsAria": "Beat sensitivity presets",
      "music.smoothingLabel": "Transition Smoothing",
      "music.scaleSmooth": "0.20 Smooth",
      "music.scalePunchy": "0.50 Punchy",
      "music.scaleInstant": "0.85 Instant Beat",
      "music.smoothingPresetsAria": "Music smoothing presets",
      "music.audioBrightness": "Modulate brightness with audio volume",

      /* Dialogos modales */
      "dialog.cancel": "Cancel",
      "dialog.addTitle": "Add Bulb by IP",
      "dialog.addSubtitle": "Connect directly to a WiZ bulb on your local network when auto-discovery doesn't find it.",
      "dialog.addIpLabel": "Bulb IP Address",
      "dialog.addNameLabel": "Bulb Name (Optional)",
      "dialog.addNamePlaceholder": "Studio Key Light",
      "dialog.addSubmit": "Add Bulb",
      "dialog.invalidIp": "Enter a valid IPv4 address (e.g. 192.168.1.45).",
      "dialog.addFailed": "Could not reach or register that fixture. Check the IP and try again.",

      "dialog.renameTitle": "Rename Fixture",
      "dialog.renameIpDisplay": "Fixture IP: {ip} ({mac})",
      "dialog.renameNameLabel": "New Fixture Name",
      "dialog.renameSubmit": "Save Name",
      "dialog.renameFailed": "Could not rename fixture. Please try again.",

      "dialog.presetSaveTitle": "Save Custom Preset",
      "dialog.presetSaveSubtitle": "Saves the current bulb state so you can recall it anytime.",
      "dialog.presetEditTitle": "Edit Custom Preset",
      "dialog.presetEditSubtitle": "Rename this preset or overwrite its parameters with the current fixture state.",
      "dialog.presetNameLabel": "Preset Label",
      "dialog.presetNamePlaceholder": "Late Night Coding",
      "dialog.presetOverwrite": "Overwrite preset parameters with current live bulb state",
      "dialog.presetSaveSubmit": "Save Preset",
      "dialog.presetUpdateSubmit": "Update Preset",
      "dialog.presetSaveFailed": "Could not save preset. Please try again.",

      /* Mensajes de estado (Status Banner) */
      "status.warning": "Warning: {error}",
      "toast.regionLabel": "Notifications",
      "toast.retry": "Retry",
      "toast.undo": "Undo",
      "toast.dismiss": "Dismiss",
      "shortcuts.openLabel": "Keyboard shortcuts",
      "shortcuts.openTitle": "Keyboard shortcuts (?)",
      "shortcuts.title": "Keyboard shortcuts",
      "shortcuts.power": "Turn selected fixtures on / off",
      "shortcuts.brightness": "Brightness \u00b15% (Shift: \u00b110%)",
      "shortcuts.colorWheel": "Adjust hue / saturation on focused color wheel",
      "shortcuts.tabs": "Switch emission mode tab",
      "shortcuts.help": "Show this help",
      "shortcuts.close": "Close",
      "status.commError": "Communication error: {error}",
      "status.connected": "Connected to local WiZ lighting service.",
      "status.scanDone": "Network scan completed.",
      "status.registeredIp": "Registered fixture at {ip}.",
      "status.renamedBulb": "Renamed {ip} to \"{name}\".",
      "status.bulbRemoved": "Removed fixture \"{name}\".",
      "status.bulbRestored": "Fixture \"{name}\" restored.",
      "status.selectionUpdated": "Updated target selection.",
      "status.multiSelectionUpdated": "Updated multi-fixture selection.",
      "status.syncedLive": "Live bulb state refreshed.",
      "status.syncedTray": "Synchronized state from system tray.",
      "status.autoSyncStep": "Live bulb state synced automatically.",
      "status.autoSyncEnabled": "Auto-sync enabled (refreshing every 3s).",
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
      "status.presetRestored": "Preset \"{name}\" restored.",
      "status.favoriteAdded": "Added \"{name}\" to tray favorite presets.",
      "status.favoriteRemoved": "Removed \"{name}\" from tray favorite presets.",
      "status.ambiStarted": "Ambilight screen sync active.",
      "status.ambiStopped": "Ambilight screen sync stopped.",
      "status.ambiDisplaySwitched": "Ambilight switched to Display {display}.",
      "status.ambiModeChanged": "Ambilight extraction mode set to {mode}.",
      "status.ambiSmoothingChanged": "Ambilight smoothing set to {alpha}.",
      "status.ambiAutoBriOn": "Ambilight automatic screen luminance enabled.",
      "status.ambiAutoBriOff": "Ambilight using manual brightness ceiling.",
      "status.ambiMinBriChanged": "Ambilight minimum brightness floor set to {floor}%.",
      "status.sceneFavAdded": "Pinned scene \"{name}\" to favorites.",
      "status.sceneFavRemoved": "Unpinned scene \"{name}\" from favorites.",
      "status.musicStarted": "Music sync active.",
      "status.musicStopped": "Music sync stopped.",
      "status.musicDeviceSwitched": "Audio output device switched.",
      "status.musicPaletteChanged": "Music palette set to {palette}.",
      "status.musicSensitivityChanged": "Beat sensitivity set to {sensitivity}x.",
      "status.musicSmoothingChanged": "Music smoothing set to {alpha}.",
      "status.musicAudioBriOn": "Dynamic beat brightness modulation enabled.",
      "status.musicAudioBriOff": "Music sync using fixed brightness ceiling.",
      "status.languageChanged": "Interface language changed to English."
    },

    es: {
      /* Titulo del documento y cabecera del riel */
      "app.windowTitle": "Consola de Iluminación Arquitectónica WiZ",
      "rail.ariaLabel": "Luminarias registradas",
      "rail.title": "Consola de Iluminación",
      "rail.subtitle": "Control local de red WiZ",
      "rail.langGroupAria": "Idioma de la interfaz",
      "theme.switcherAria": "Tema de la interfaz",
      "theme.stoneShort": "Claro",
      "theme.darkShort": "Oscuro",
      "theme.stoneTooltip": "Tema claro",
      "theme.darkTooltip": "Tema oscuro",
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
      "rail.renameAria": "Renombrar {name}",
      "rail.removeAria": "Eliminar {name}",
      "rail.powerToggleOnAria": "Apagar {name}",
      "rail.powerToggleOffAria": "Encender {name}",
      "rail.syncNowBtn": "Sincronizar",
      "rail.syncNowTitle": "Actualizar el estado en vivo de todas las luminarias",
      "rail.autoSync": "Auto-sinc (3s)",
      "rail.statusReady": "Listo para el control local de WiZ.",
      "rail.openDrawerAria": "Abrir panel de luminarias y red",
      "rail.closeDrawerAria": "Cerrar panel de luminarias",

      /* Cabecera del escenario fotometrico */
      "stage.ariaLabel": "Controles de parámetros lumínicos",
      "stage.noFixture": "Ninguna luminaria seleccionada",
      "stage.noneSelected": "Ninguna luminaria seleccionada",
      "stage.stateNoneSelected": "Sin objetivo",
      "stage.emptyNoBulbs": "Todavía no hay focos WiZ registrados. Escanea la red local o agrega uno por IP.",
      "stage.emptyNoSelection": "No hay luminarias seleccionadas. Selecciona al menos una para controlar la iluminación.",
      "stage.stateStreamingAmbi": "Transmitiendo · Ambilight",
      "stage.stateStreamingMusic": "Transmitiendo · Sincronización Musical",
      "stage.controllingMany": "Controlando {count} luminarias ({name} principal)",
      "stage.controllingList": "Controlando {count} luminarias: {names}",
      "stage.stateOffline": "Sin conexión",
      "stage.stateOff": "Apagado",
      "stage.stateOffStandby": "Apagado · En espera ({brightness}%)",
      "stage.stateOnRgb": "Encendido · RGB ({r}, {g}, {b}) · {brightness}%",
      "stage.stateOnScene": "Encendido · Escena: {scene} · {brightness}%",
      "stage.stateOnKelvin": "Encendido · {kelvin} K · {brightness}%",
      "stage.saveStateBtn": "Guardar estado actual",
      "stage.saveStateTitle": "Guardar el estado actual de la luminaria como preset",
      "stage.turnOn": "Encender",
      "stage.turnOff": "Apagar",

      /* Temporizador de apagado (Sleep Timer) */
      "sleep.title": "Temporizador de apagado",
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
      "dimming.title": "Brillo",
      "dimming.sliderAria": "Porcentaje de brillo maestro",
      "dimming.presetsAria": "Niveles rápidos de brillo",

      /* Pestanas de modo */
      "tabs.ariaLabel": "Modo de emisión lumínica",
      "tabs.rgb": "Color",
      "tabs.temperature": "Blanco",
      "tabs.scene": "Escenas",
      "tabs.custom": "Presets",
      "tabs.customWithCount": "Presets ({count})",
      "tabs.ambilight": "Ambilight",
      "tabs.music": "Música",

      /* Panel 1: RGB */
      "rgb.wheelAria": "Rueda de color HSV interactiva",
      "rgb.wheelValueText": "Tono {hue}°, Saturación {saturation}%",
      "rgb.manualCaption": "Valores RGB y código hex de precisión",
      "rgb.redLabel": "Rojo (0-255)",
      "rgb.greenLabel": "Verde (0-255)",
      "rgb.blueLabel": "Azul (0-255)",
      "rgb.hexLabel": "Código hex",
      "rgb.applyBtn": "Aplicar RGB",
      "rgb.swatchesCaption": "Muestras cromáticas de referencia",
      "rgb.swatchesAria": "Muestras RGB seleccionadas",
      "rgb.swatchSodium": "Ámbar Sodio",
      "rgb.swatchCrimson": "Láser Carmesí",
      "rgb.swatchUltraviolet": "Ultravioleta",
      "rgb.swatchCerulean": "Cielo Cerúleo",
      "rgb.swatchMint": "Menta Fósforo",
      "rgb.swatchHalogen": "Oro Halógeno",

      /* Panel 2: Temperatura Kelvin */
      "kelvin.title": "Temperatura de Color",
      "kelvin.description": "Ajusta la calidez desde 2200 K luz cálida hasta 6500 K luz de día fría.",
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
      "custom.title": "Presets Guardados",
      "custom.description": "Guarda cualquier color, temperatura de blanco o escena con su brillo para reutilizarlos al instante.",
      "custom.gridAria": "Presets de iluminación guardados",
      "custom.emptyTitle": "Aún no hay presets guardados.",
      "custom.emptySubtitle": "Configura cualquier color, temperatura Kelvin o escena y haz clic en Guardar estado actual.",
      "custom.applyAria": "Aplicar preset {name}",
      "custom.summaryScene": "Escena: {scene} · {brightness}%",
      "custom.favoriteRemoveTitle": "Quitar de Presets favoritos en la bandeja del sistema",
      "custom.favoriteAddTitle": "Agregar a Presets favoritos en la bandeja del sistema",
      "custom.favoritedBtn": "En favoritos",
      "custom.favoriteBtn": "Favorito",
      "custom.applyBtn": "Aplicar",
      "custom.editBtn": "Editar",
      "custom.deleteBtn": "Eliminar",

      /* Panel 5: Ambilight */
      "ambi.statusStandby": "EN ESPERA",
      "ambi.statusLive": "EN VIVO",
      "ambi.telemetryZero": "0 FPS · 0 fotogramas",
      "ambi.telemetryFpsFrames": "{fps} FPS · {count} fotogramas",
      "ambi.swatchTitle": "Color Detectado en Pantalla",
      "ambi.startBtn": "Iniciar Ambilight",
      "ambi.stopBtn": "Detener Ambilight",
      "ambi.sourceLabel": "Pantalla de Origen",
      "ambi.defaultDisplay": "Pantalla 1 (Principal)",
      "ambi.displayItem": "Pantalla {index} ({width}x{height})",
      "ambi.allDisplays": "Todas las pantallas ({width}x{height})",
      "ambi.modeLabel": "Modo de Extracción de Color",
      "ambi.modeVibrant": "Vibrante / Dominante",
      "ambi.modeAverage": "Color Promedio de Pantalla",
      "ambi.smoothingLabel": "Suavizado de Transición",
      "ambi.scaleCinematic": "0.15 Cinematográfico",
      "ambi.scaleBalanced": "0.38 Equilibrado",
      "ambi.scaleFast": "0.75 Respuesta Rápida",
      "ambi.smoothingPresetsAria": "Preajustes de suavizado",
      "ambi.autoBrightness": "Ajustar el brillo automáticamente según la pantalla",
      "ambi.minBrightnessLabel": "Piso Mínimo de Brillo",
      "ambi.minBrightnessHint": "Evita que escenas oscuras atenúen la luminaria por debajo de este umbral.",

      /* Panel 6: Music Sync */
      "music.statusStandby": "EN ESPERA",
      "music.statusLive": "EN VIVO",
      "music.telemetryZero": "0 FPS · 0 fotogramas",
      "music.telemetryFpsFrames": "{fps} FPS · {count} fotogramas",
      "music.swatchTitle": "Color de Audio en Vivo",
      "music.metersAria": "Medidores de frecuencia de audio en tiempo real",
      "music.bassLabel": "Graves (20-250 Hz)",
      "music.midLabel": "Medios (250-2k Hz)",
      "music.trebleLabel": "Agudos (2k-12k Hz)",
      "music.rmsLabel": "Nivel de Volumen",
      "music.startBtn": "Iniciar Sincronización Musical",
      "music.stopBtn": "Detener Sincronización Musical",
      "music.deviceLabel": "Dispositivo de Salida de Audio",
      "music.defaultDevice": "Salida de audio predeterminada",
      "music.defaultPrefix": "Predeterminado",
      "music.paletteLabel": "Paleta de Color",
      "music.paletteSpectrum": "Espectro (Graves/Medios/Agudos)",
      "music.paletteClub": "Pulso Club (Cálido/Neón)",
      "music.paletteChill": "Aurora Chill (Océano/Turquesa)",
      "music.sensitivityLabel": "Sensibilidad al Ritmo",
      "music.scaleSubtle": "0.4x Sutil",
      "music.scaleBalanced": "1.0x Equilibrado",
      "music.scaleHighGain": "2.5x Alta Ganancia",
      "music.sensitivityPresetsAria": "Preajustes de sensibilidad al ritmo",
      "music.smoothingLabel": "Suavizado de Transición",
      "music.scaleSmooth": "0.20 Suave",
      "music.scalePunchy": "0.50 Dinámico",
      "music.scaleInstant": "0.85 Pulso Instantáneo",
      "music.smoothingPresetsAria": "Preajustes de suavizado musical",
      "music.audioBrightness": "Modular el brillo con el volumen de audio",

      /* Dialogos modales */
      "dialog.cancel": "Cancelar",
      "dialog.addTitle": "Agregar Luminaria por IP",
      "dialog.addSubtitle": "Conecta directamente un foco WiZ en tu red local cuando el escaneo automático no lo encuentra.",
      "dialog.addIpLabel": "Dirección IP de la Luminaria",
      "dialog.addNameLabel": "Nombre de la Luminaria (Opcional)",
      "dialog.addNamePlaceholder": "Luz Principal de Estudio",
      "dialog.addSubmit": "Agregar Luminaria",
      "dialog.invalidIp": "Ingresa una dirección IPv4 válida (ej. 192.168.1.45).",
      "dialog.addFailed": "No se pudo contactar o registrar la luminaria. Verifica la IP e intenta de nuevo.",

      "dialog.renameTitle": "Renombrar Luminaria",
      "dialog.renameIpDisplay": "IP de la luminaria: {ip} ({mac})",
      "dialog.renameNameLabel": "Nuevo Nombre de la Luminaria",
      "dialog.renameSubmit": "Guardar Nombre",
      "dialog.renameFailed": "No se pudo renombrar la luminaria. Intenta de nuevo.",

      "dialog.presetSaveTitle": "Guardar Preset",
      "dialog.presetSaveSubtitle": "Guarda el estado actual de la luminaria para recuperarlo en cualquier momento.",
      "dialog.presetEditTitle": "Editar Preset",
      "dialog.presetEditSubtitle": "Renombra este preset o sobrescribe sus ajustes con el estado actual de la luminaria.",
      "dialog.presetNameLabel": "Nombre del Preset",
      "dialog.presetNamePlaceholder": "Programación Nocturna",
      "dialog.presetOverwrite": "Sobrescribir parámetros con el estado en vivo actual de la luminaria",
      "dialog.presetSaveSubmit": "Guardar Preset",
      "dialog.presetUpdateSubmit": "Actualizar Preset",
      "dialog.presetSaveFailed": "No se pudo guardar el preset. Intenta de nuevo.",

      /* Mensajes de estado (Status Banner) */
      "status.warning": "Advertencia: {error}",
      "toast.regionLabel": "Notificaciones",
      "toast.retry": "Reintentar",
      "toast.undo": "Deshacer",
      "toast.dismiss": "Cerrar",
      "shortcuts.openLabel": "Atajos de teclado",
      "shortcuts.openTitle": "Atajos de teclado (?)",
      "shortcuts.title": "Atajos de teclado",
      "shortcuts.power": "Encender / apagar las luminarias seleccionadas",
      "shortcuts.brightness": "Brillo \u00b15% (Shift: \u00b110%)",
      "shortcuts.colorWheel": "Ajustar tono / saturación en la rueda enfocada",
      "shortcuts.tabs": "Cambiar de pesta\u00f1a de modo",
      "shortcuts.help": "Mostrar esta ayuda",
      "shortcuts.close": "Cerrar",
      "status.commError": "Error de comunicación: {error}",
      "status.connected": "Conectado al servicio local de iluminación WiZ.",
      "status.scanDone": "Escaneo de red completado.",
      "status.registeredIp": "Luminaria registrada en {ip}.",
      "status.renamedBulb": "Luminaria {ip} renombrada a \"{name}\".",
      "status.bulbRemoved": "Luminaria \"{name}\" eliminada.",
      "status.bulbRestored": "Luminaria \"{name}\" restaurada.",
      "status.selectionUpdated": "Selección de luminarias actualizada.",
      "status.multiSelectionUpdated": "Selección múltiple de luminarias actualizada.",
      "status.syncedLive": "Estado en vivo de las luminarias actualizado.",
      "status.syncedTray": "Estado sincronizado desde la bandeja del sistema.",
      "status.autoSyncStep": "Estado de las luminarias sincronizado automáticamente.",
      "status.autoSyncEnabled": "Auto-sincronización activada (actualización cada 3 s).",
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
      "status.presetSaved": "Preset \"{name}\" guardado.",
      "status.presetUpdated": "Preset \"{name}\" actualizado.",
      "status.presetApplied": "Preset \"{name}\" aplicado.",
      "status.presetDeleted": "Preset \"{name}\" eliminado.",
      "status.presetRestored": "Preset \"{name}\" restaurado.",
      "status.favoriteAdded": "\"{name}\" agregado a Presets favoritos en la bandeja.",
      "status.favoriteRemoved": "\"{name}\" quitado de Presets favoritos en la bandeja.",
      "status.ambiStarted": "Sincronización de pantalla Ambilight activa.",
      "status.ambiStopped": "Sincronización de pantalla Ambilight detenida.",
      "status.ambiDisplaySwitched": "Ambilight cambiado a la pantalla {display}.",
      "status.ambiModeChanged": "Modo de extracción Ambilight cambiado a {mode}.",
      "status.ambiSmoothingChanged": "Suavizado de Ambilight ajustado a {alpha}.",
      "status.ambiAutoBriOn": "Luminancia automática de pantalla Ambilight activada.",
      "status.ambiAutoBriOff": "Ambilight usando límite de brillo manual.",
      "status.ambiMinBriChanged": "Piso mínimo de brillo Ambilight ajustado al {floor}%.",
      "status.sceneFavAdded": "Escena \"{name}\" fijada en favoritas.",
      "status.sceneFavRemoved": "Escena \"{name}\" quitada de favoritas.",
      "status.musicStarted": "Sincronización musical activa.",
      "status.musicStopped": "Sincronización musical detenida.",
      "status.musicDeviceSwitched": "Dispositivo de salida de audio cambiado.",
      "status.musicPaletteChanged": "Paleta musical cambiada a {palette}.",
      "status.musicSensitivityChanged": "Sensibilidad al ritmo ajustada a {sensitivity}x.",
      "status.musicSmoothingChanged": "Suavizado musical ajustado a {alpha}.",
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

    scope.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      const key = el.getAttribute("data-i18n-aria");
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

  if (typeof document !== "undefined" && document.documentElement) {
    const bootLang =
      (document.documentElement.dataset && document.documentElement.dataset.lang) ||
      document.documentElement.lang ||
      "en";
    const resolvedBootLang = setLanguage(bootLang);
    if (resolvedBootLang !== "en") {
      translateDom(document);
    }
  }
})();
