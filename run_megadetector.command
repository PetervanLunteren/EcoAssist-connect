#!/usr/bin/env bash

# catch arguments
ROOT_DIR=${1}
CONDA_DIR=${2}
DET_THRESH=${3}
ECO_PATH=${4}

# change directory
cd "${ROOT_DIR}"

# set variables
BS_ENV="${CONDA_DIR}/envs/ecoassistcondaenv-base"
MD_ENV="${CONDA_DIR}/envs/ecoassistcondaenv-base"

# activate conda env for classification
source "${CONDA_DIR}/etc/profile.d/conda.sh"
source "${CONDA_DIR}/bin/activate" base
export PATH="${CONDA_DIR}/bin":$PATH
conda deactivate
conda activate "${MD_ENV}"

# add ecoassist folder to path
export PATH="${ECO_PATH}/cameratraps:$PATH"
export PYTHONPATH="$PYTHONPATH:${ECO_PATH}/cameratraps:${ECO_PATH}/cameratraps/megadetector:${ECO_PATH}/yolov5"

# run script
python "${ECO_PATH}/cameratraps/megadetector/detection/run_detector_batch.py" "${ROOT_DIR}/models/megadetector/md_v5a.0.0.pt" "${ROOT_DIR}/temp/org" "${ROOT_DIR}/temp/org/image_recognition_file.json" --threshold "${DET_THRESH}" --output_relative_filenames --quiet

# switch back to base env
conda deactivate
conda activate "${BS_ENV}"
