@echo off

rem catch arguments
set "ROOT_DIR=%~1"
set "CONDA_DIR=%~2"
set "DET_THRESH=%~3"

rem change directory
cd /d "%ROOT_DIR%"

rem set variables
set BS_ENV=ecoassistcondaenv-base
set MD_ENV=ecoassistcondaenv-base

rem activate conda env for identification
call "%CONDA_DIR%\Scripts\activate.bat" "%CONDA_DIR%"
call conda deactivate
call conda activate "%MD_ENV%"

rem add ecoassist folder to path
set PATH=%ROOT_DIR%\cameratraps;%PATH%
set PYTHONPATH=%PYTHONPATH%;%ROOT_DIR%\cameratraps;%ROOT_DIR%\yolov5

rem run script
python "%ROOT_DIR%\cameratraps\detection\run_detector_batch.py" "%ROOT_DIR%\md_v5a.0.0.pt" "%ROOT_DIR%\temp\org" "%ROOT_DIR%\temp\org\image_recognition_file.json" --threshold "%DET_THRESH%" --output_relative_filenames --quiet

rem switch back to base env
call conda deactivate
call conda activate "%BS_ENV%"
