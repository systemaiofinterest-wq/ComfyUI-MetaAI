@echo off
setlocal EnableDelayedExpansion
title Instalador FFmpeg V3 (Correccion de Path)
color 0A

:: ==========================================
:: 1. VERIFICAR PERMISOS DE ADMINISTRADOR
:: ==========================================
net session >nul 2>&1
if %errorLevel% neq 0 (
    color 0C
    echo [ERROR] NECESITAS PERMISOS DE ADMINISTRADOR.
    echo Haz clic derecho y elige "Ejecutar como administrador".
    pause
    exit
)

:: ==========================================
:: 2. CONFIGURACION
:: ==========================================
set "FFMPEG_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-git-full.7z"
set "DEST_DIR=C:\ffmpeg"
set "TEMP_DIR=%TEMP%\ffmpeg_setup_v3"
set "ARCHIVE_NAME=ffmpeg.7z"
set "FFMPEG_BIN=C:\ffmpeg\bin"

:: Buscar WinRAR
if exist "C:\Program Files\WinRAR\WinRAR.exe" (
    set "WINRAR=C:\Program Files\WinRAR\WinRAR.exe"
) else if exist "C:\Program Files (x86)\WinRAR\WinRAR.exe" (
    set "WINRAR=C:\Program Files (x86)\WinRAR\WinRAR.exe"
) else (
    echo [ERROR] No se encontro WinRAR.
    pause
    exit
)

:: ==========================================
:: 3. INSTALACION (Si ya existe, omite descarga)
:: ==========================================
if exist "%DEST_DIR%\bin\ffmpeg.exe" (
    echo [INFO] FFmpeg ya existe en C:\ffmpeg. Saltando descarga...
    goto :CONFIGURAR_PATH
)

echo Creando carpetas temporales...
if exist "%TEMP_DIR%" rd /s /q "%TEMP_DIR%"
mkdir "%TEMP_DIR%"

echo.
echo [1/3] Descargando FFmpeg (con barra de progreso)...
curl -L --progress-bar -o "%TEMP_DIR%\%ARCHIVE_NAME%" "%FFMPEG_URL%"

echo.
echo [2/3] Descomprimiendo...
"%WINRAR%" x -y -ibck "%TEMP_DIR%\%ARCHIVE_NAME%" "%TEMP_DIR%\"

echo.
echo [3/3] Instalando en C:\ffmpeg...
if exist "%DEST_DIR%" rd /s /q "%DEST_DIR%"
for /d %%I in ("%TEMP_DIR%\ffmpeg-*") do (
    move "%%I" "%DEST_DIR%" >nul
)

:: Limpieza
rd /s /q "%TEMP_DIR%"

:CONFIGURAR_PATH
:: ==========================================
:: 4. ARREGLO DE VARIABLES DE ENTORNO
:: ==========================================
echo.
echo --------------------------------------------------------
echo CONFIGURANDO VARIABLES DE ENTORNO (PATH)
echo --------------------------------------------------------

:: A) Agregamos al PATH del USUARIO (User) - Lo que ves en tu captura
echo 1. Agregando a variables de USUARIO...
powershell -Command "$p=[Environment]::GetEnvironmentVariable('Path', 'User'); if ($p -notlike '*%FFMPEG_BIN%*') { [Environment]::SetEnvironmentVariable('Path', $p + ';%FFMPEG_BIN%', 'User'); Write-Host '   [OK] Agregado a Usuario.' -Fore Green } else { Write-Host '   [YA EXISTE] En Usuario.' -Fore Yellow }"

:: B) Agregamos al PATH del SISTEMA (Machine) - Para todos los usuarios
echo 2. Agregando a variables de SISTEMA...
powershell -Command "$p=[Environment]::GetEnvironmentVariable('Path', 'Machine'); if ($p -notlike '*%FFMPEG_BIN%*') { [Environment]::SetEnvironmentVariable('Path', $p + ';%FFMPEG_BIN%', 'Machine'); Write-Host '   [OK] Agregado a Sistema.' -Fore Green } else { Write-Host '   [YA EXISTE] En Sistema.' -Fore Yellow }"

:: C) Forzamos el PATH en la sesión actual para que la prueba funcione YA
set "PATH=%PATH%;%FFMPEG_BIN%"

echo.
echo ========================================================
echo      INSTALACION Y CONFIGURACION FINALIZADA
echo ========================================================
echo.
echo Iniciando prueba de version...
echo.

:: Verificamos directamente aquí
ffmpeg -version | findstr "ffmpeg version"
if %errorlevel% equ 0 (
    echo.
    echo [EXITO] FFmpeg esta instalado y funcionando correctamente.
) else (
    echo [ERROR] Aun no se detecta. Reinicia tu PC.
)

echo.
echo Presiona cualquier tecla para salir...
pause >nul