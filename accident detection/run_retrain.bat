@echo off
echo ==================================================
echo      IncidentIQ - YOLO Model Retraining
echo ==================================================
echo.
echo This script will:
echo 1. Convert 'False Alarm' feedback into a dataset.
echo 2. Fine-tune the YOLO model to ignore those patterns.
echo 3. Save a new model file.
echo.
pause

python retrain.py

echo.
echo ==================================================
echo                 DONE
echo ==================================================
pause
