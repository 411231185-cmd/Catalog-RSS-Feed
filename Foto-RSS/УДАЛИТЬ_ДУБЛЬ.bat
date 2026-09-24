@echo off
chcp 65001 > nul
set "FILE=C:\GitHub-Repositories\Foto-RSS\JPG\Foto-Atalonnyje-RSS\Все фото после генерации\Directus-Foto\Колесо червячное 1М63.04.120.jpg"
if exist "%FILE%" (
    del /F "%FILE%"
    echo Удалён: Колесо червячное 1М63.04.120.jpg
) else (
    echo Файл не найден - возможно уже удалён
)
pause
