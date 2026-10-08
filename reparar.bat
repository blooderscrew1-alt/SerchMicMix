@echo off
rem ============================================================
rem  Serch MicMix - reparar
rem
rem  Se usa cuando la aplicacion no arranca por un problema con
rem  PySide6, sounddevice o numpy. El caso tipico es:
rem
rem      DLL load failed while importing _multiarray_umath
rem
rem  Comprueba cual falla, lo reinstala a la fuerza y, si numpy
rem  sigue fallando, revisa e instala el redistribuible de
rem  Microsoft Visual C++ 2015-2022.
rem
rem  Todo el detalle queda en reparar.txt
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Serch MicMix - reparar

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
"%PY%" "%~dp0herramientas\salud.py" --reparar --salida "%~dp0reparar.txt"

echo.
echo  ============================================================
echo   Informe guardado en:
echo     %~dp0reparar.txt
echo  ============================================================
echo.
pause
endlocal
exit /b 0
