@echo off
rem ============================================================
rem  Busca un Python que funcione y deja su ruta completa en la
rem  variable PY. Se usa asi:
rem
rem      call "%~dp0herramientas\_buscar_python.bat"
rem
rem  NO lleva setlocal a proposito: la variable PY tiene que
rem  quedar disponible en el archivo que hace la llamada.
rem
rem  Se prefiere el primer Python que funcione Y que ademas ya
rem  tenga las tres dependencias. Las rutas se citan siempre
rem  entre comillas porque es facil que Python este en una carpeta
rem  con espacios (por ejemplo "C:\Program Files\...").
rem
rem  Se miran tambien las carpetas tipicas donde instala python.org,
rem  porque en un PC con un procesador antiguo puede hacer falta un
rem  Python mas viejo (3.12) que no este en el PATH.
rem ============================================================
set "PY="
set "PY_SIN_DEPS="

for %%C in (python.exe python3.exe) do (
    for /f "delims=" %%P in ('where %%C 2^>nul') do call :buscar_probar "%%P"
)
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do call :buscar_probar "%%P"

for %%D in ("%LOCALAPPDATA%\Programs\Python" "%ProgramFiles%\Python" "%ProgramFiles(x86)%\Python") do (
    for /d %%V in ("%%~D\Python3*") do call :buscar_probar "%%~V\python.exe"
)
for /d %%V in ("C:\Python3*") do call :buscar_probar "%%~V\python.exe"

if not defined PY if defined PY_SIN_DEPS set "PY=%PY_SIN_DEPS%"
goto :eof


:buscar_probar
set "CAND=%~1"
if "%CAND%"=="" goto :eof
if not exist "%CAND%" goto :eof
rem Se descarta el aviso de la Microsoft Store: no es un Python real.
echo "%CAND%" | findstr /i "WindowsApps" >nul && goto :eof
"%CAND%" -c "import sys" >nul 2>nul || goto :eof
if not defined PY_SIN_DEPS set "PY_SIN_DEPS=%CAND%"
if defined PY goto :eof
"%CAND%" -c "import PySide6, sounddevice, numpy" >nul 2>nul && set "PY=%CAND%"
goto :eof
