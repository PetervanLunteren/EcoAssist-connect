@echo off

rem catch arguments
set "ROOT_DIR=%~1"
set "CONDA_DIR=%~2"
set "CLS_THRESH=%~3"

rem change directory
cd /d "%ROOT_DIR%"

rem set variables
set BS_ENV=ecoassistcondaenv-base
set DF_ENV=ecoassistcondaenv-pytorch
set MODEL_PATH=%ROOT_DIR%\deepfaune\deepfaune-vit_large_patch14_dinov2.lvd142m.pt
set JSON_PATH=%ROOT_DIR%\temp\org\image_recognition_file.json

@REM rem activate conda env for classification
@REM call "%CONDA_DIR%\etc\profile.d\conda.bat"
@REM call "%CONDA_DIR%\Scripts\activate" base
@REM set "PATH=%CONDA_DIR%\Scripts;%PATH%"
@REM call conda deactivate
@REM call conda activate "%DF_ENV%"

rem activate conda env for identification
call "%CONDA_DIR%\Scripts\activate.bat" "%CONDA_DIR%"
call conda deactivate
call conda activate "%DF_ENV%"

rem add ecoassist folder to path
set PATH=%ROOT_DIR%\cameratraps;%PATH%
set PYTHONPATH=%PYTHONPATH%;%ROOT_DIR%\cameratraps;%ROOT_DIR%\yolov5

rem run script
python "%ROOT_DIR%\EcoAssist\classification_utils\model_types\deepfaune\classify_detections.py" "%ROOT_DIR%" "%MODEL_PATH%" "0.1" "%CLS_THRESH%" "False" "%JSON_PATH%" "None"

rem switch back to base env
call conda deactivate
call conda activate "%BS_ENV%"
