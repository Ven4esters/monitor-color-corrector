@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Works both in a checkout and as a single file in an empty writable folder.
pushd "%~dp0" || (echo Cannot open the launcher directory. & exit /b 1)
for /f "tokens=2 delims=:" %%C in ('chcp') do set "SPECTRA_OLD_CP=%%C"
chcp 65001 >nul
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_REQUIRE_VIRTUALENV=true"
set "VPY=.venv\Scripts\python.exe"
set "CHECK312=import struct, sys; sys.exit(not (sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8))"
set "TRIED_WINGET="
set "REV=105d52141255d06e6d49fc6d1aa2962f89cb3a9c"
set "APP_VERSION=1.1.1"
set "QT_VERSION=6.10.3"
echo Spectra Studio  /  Desktop
if exist "%VPY%" goto check_env
if exist ".venv" goto bad_env

:find_python
set "BASE=py.exe"
set "BASE_ARGS=-3.12"
"%BASE%" %BASE_ARGS% -I -c "%CHECK312%" >nul 2>&1
if not errorlevel 1 goto create_env
set "BASE_ARGS="
set "BASE=%LocalAppData%\Programs\Python\Python312\python.exe"
"%BASE%" -I -c "%CHECK312%" >nul 2>&1
if not errorlevel 1 goto create_env
set "BASE=python.exe"
"%BASE%" -I -c "%CHECK312%" >nul 2>&1
if not errorlevel 1 goto create_env
if defined TRIED_WINGET goto missing_python
if defined CI goto missing_python
if defined SPECTRA_NO_PAUSE goto missing_python
where winget.exe >nul 2>&1
if errorlevel 1 goto missing_python
echo Не найден 64-битный Python 3.12. Можно установить его для текущего пользователя через winget.
choice /C YN /N /M "Установить Python.Python.3.12? [Y/N] "
if not "%errorlevel%"=="1" goto missing_python
set "TRIED_WINGET=1"
winget install --exact --id Python.Python.3.12 --source winget --scope user
if errorlevel 1 goto missing_python
goto find_python

:create_env
echo [1/3] Создаю изолированное окружение .venv ...
"%BASE%" %BASE_ARGS% -I -X utf8 -m venv ".venv"
if errorlevel 1 goto env_failed

:check_env
"%VPY%" -I -c "%CHECK312%" >nul 2>&1
if errorlevel 1 goto bad_env
"%VPY%" -I -c "import sys; sys.exit(sys.prefix == sys.base_prefix)" >nul 2>&1
if errorlevel 1 goto bad_env
echo [1/3] Окружение Python 3.12 готово.
rem The remote copy is pinned, not an arbitrary future version of the branch.
set "SPEC=spectra-display-studio[desktop] @ https://codeload.github.com/Ven4esters/monitor-color-corrector/zip/%REV%"
set "EDITABLE="
set "BUILD_ID=archive-%REV%"
if not exist "pyproject.toml" goto dependencies
if not exist "spectra\desktop\__main__.py" goto dependencies
if not exist "spectra\web\assets\alpine-lake.jpg" goto dependencies
set "SPEC=.[desktop]"
set "EDITABLE=--editable"
set "BUILD_ID=checkout-%APP_VERSION%-qt%QT_VERSION%"

:dependencies
if not exist ".venv\spectra-build.txt" goto install
findstr /L /X /C:"%BUILD_ID%" ".venv\spectra-build.txt" >nul 2>&1
if errorlevel 1 goto install
call :verify >nul 2>&1
if errorlevel 1 goto install
echo [2/3] Компоненты готовы. Повторная загрузка не нужна.
goto launch

:install
echo [2/3] Устанавливаю приложение, PySide6 и ресурсы. Для первого запуска нужен интернет.
"%VPY%" -I -X utf8 -m pip --version >nul 2>&1
if not errorlevel 1 goto pip_ready
"%VPY%" -I -X utf8 -m ensurepip --upgrade
if errorlevel 1 goto install_failed
:pip_ready
"%VPY%" -I -X utf8 -m pip install --force-reinstall --disable-pip-version-check --only-binary=PySide6-Essentials,shiboken6 %EDITABLE% "%SPEC%"
if errorlevel 1 goto install_failed
call :verify
if errorlevel 1 goto install_failed
>".venv\spectra-build.txt" echo %BUILD_ID%
if errorlevel 1 goto env_failed

:launch
echo [3/3] Запускаю настольное окно Spectra Studio ...
"%VPY%" -I -X utf8 -m spectra.desktop %*
set "RC=%errorlevel%"
if "%RC%"=="0" goto finish
echo Приложение завершилось с ошибкой. Сообщение выше поможет определить причину.
goto wait_on_error

:verify
rem Verify the actual Qt imports and installed resources, not just a marker file.
"%VPY%" -I -c "import sys; from importlib.metadata import version; from importlib.resources import files; from spectra.desktop.window import Window; from spectra.desktop.ui import ASSETS; desktop=files('spectra.desktop'); sys.exit(not (version('spectra-display-studio')=='%APP_VERSION%' and version('PySide6-Essentials')==version('shiboken6')=='%QT_VERSION%' and all(ASSETS.joinpath(n).is_file() for n in ('alpine-lake.jpg','brand.svg','icons.svg','monitor-violet.svg','monitor-aqua.svg')) and all(desktop.joinpath(n).is_file() for n in ('theme.qss','chevron.svg'))))"
exit /b %errorlevel%

:missing_python
echo Нужен 64-битный Python 3.12 с модулями venv и pip. Установите его и снова откройте этот файл.
echo Команда установки: winget install --exact --id Python.Python.3.12 --scope user
goto failed
:bad_env
echo Существующая .venv повреждена или создана не 64-битным Python 3.12.
echo Ничего не удалено. Закройте приложение, переименуйте .venv и повторите запуск.
goto failed
:env_failed
echo Не удалось подготовить .venv. Проверьте свободное место и право записи в папку .bat.
goto failed
:install_failed
echo Не удалось установить или проверить компоненты. Приложение не запущено.
echo Проверьте доступ к PyPI и GitHub. Можно распаковать проект целиком и запустить .bat рядом с pyproject.toml.
:failed
set "RC=1"
:wait_on_error
if not defined CI if not defined SPECTRA_NO_PAUSE pause
:finish
if defined SPECTRA_OLD_CP chcp %SPECTRA_OLD_CP% >nul
popd
endlocal & exit /b %RC%
