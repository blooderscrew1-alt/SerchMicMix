@echo off
rem ============================================================
rem  Serch MicMix - diagnostico
rem  Genera diagnostico.txt con todo lo necesario para saber por
rem  que la aplicacion no arranca.
rem  El trabajo pesado lo hace herramientas\salud.py
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Serch MicMix - diagnostico

call "%~dp0herramientas\_buscar_python.bat"

if not defined PY (
    echo.
    echo  [!] No se encontro ningun Python que funcione en este equipo.
    echo.
    echo      Descarga Python 3.9 o superior desde:
    echo        https://www.python.org/downloads/windows/
    echo      y marca la casilla "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo  Python: "%PY%"
echo.
"%PY%" "%~dp0herramientas\salud.py" --salida "%~dp0diagnostico.txt"

echo.
echo  ============================================================
echo   Informe guardado en:
echo     %~dp0diagnostico.txt
echo  ============================================================
echo.
pause
endlocal
exit /b 0
