@echo off
rem ============================================================
rem  AudioMix - lanzador
rem  Busca un Python que funcione, se asegura de que estan las
rem  dependencias y abre la aplicacion.
rem
rem  Si algo falla, usa diagnostico.bat o reparar.bat.
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AudioMix

rem --- 1. Localizar un Python valido -------------------------------------
call "%~dp0herramientas\_buscar_python.bat"

if not defined PY (
    echo.
    echo  [!] No se encontro ningun Python que funcione en este equipo.
    echo.
    echo      1. Descarga Python 3.9 o superior desde:
    echo         https://www.python.org/downloads/windows/
    echo      2. Durante la instalacion marca la casilla
    echo         "Add python.exe to PATH".
    echo      3. Vuelve a ejecutar run.bat.
    echo.
    pause
    exit /b 1
)

echo  Python encontrado: "%PY%"

rem --- 2. Dependencias ---------------------------------------------------
"%PY%" -c "import PySide6, sounddevice, numpy" >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Faltan dependencias o alguna no carga bien. Instalando...
    echo.
    "%PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    "%PY%" -c "import PySide6, sounddevice, numpy" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo  ============================================================
        echo   [!] Alguna dependencia no funciona todavia.
        echo  ============================================================
        echo.
        echo   Esto NO suele ser un problema de Internet. La causa mas
        echo   habitual es que numpy no consigue cargar sus DLL porque
        echo   falta el redistribuible de Microsoft Visual C++ 2015-2022.
        echo.
        echo   Ejecuta REPARAR.bat: comprueba que falla exactamente, lo
        echo   reinstala y, si hace falta, instala ese componente.
        echo.
        echo   Si quieres el detalle completo, ejecuta DIAGNOSTICO.bat.
        echo.
        pause
        exit /b 1
    )
)

rem --- 3. Arrancar sin consola si es posible -----------------------------
rem  La aplicacion se lanza desacoplada y con la salida estandar cerrada,
rem  para que este .bat termine de inmediato.
set "PYW="
for %%P in ("%PY%") do if exist "%%~dpPpythonw.exe" set "PYW=%%~dpPpythonw.exe"

if defined PYW (
    start "AudioMix" "!PYW!" "%~dp0main.py" %* <nul >nul 2>nul
) else (
    "%PY%" "%~dp0main.py" %*
)
endlocal
exit /b 0
