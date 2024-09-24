# EcoAssist connect
# Analyse images in real time and send notifications 
# Peter van Lunteren, 24 Sept 2024

# TODO: put admin csv, project csv's, etc etc in fixed folders so I can quickly download them via url
# TODO: clean saved images every week after the report is sent
# TODO: save daily report in the project folder
# TODO: adjust the bat files with new img_dir so it works on windows too
# TODO: volgens mij returned the inference functie altijd True, ook als ie ergens errort. Return False als er een error is
# TODO: make script a service on the ubuntu server

###########################################
############ INITIALIZE SCRIPT ############
###########################################

# import
import os
import time
import cv2
import csv
import imaplib
import torch
import uuid
import email
from email.header import decode_header
from PIL import Image
from io import BytesIO
import io
import datetime
import PIL.ExifTags
import json
from PIL import Image, TiffImagePlugin
from GPSPhoto import gpsphoto
import base64
import requests
import base64
import requests
import json
import traceback
import piexif
import platform
from PIL import Image
import cv2
from pathlib import Path
import shutil
import re
import pandas as pd
import pytesseract
import email, smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
import retrying
from twilio.base.exceptions import TwilioException
from subprocess import Popen
import subprocess
import sys

# set working directory to file location
curr_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(curr_dir)

# init vars
# fpath_vis_img = os.path.join(curr_dir, 'temp', 'vis', 'visualized.jpg')
fpath_output_dir = os.path.join(curr_dir, 'output')
fpath_log_file = os.path.join(fpath_output_dir, 'log.txt')
fpath_daily_report_csv = os.path.join(fpath_output_dir, 'daily_output.csv')
fpath_observations_csv = os.path.join(fpath_output_dir, 'results_detections.csv')
fpath_project_specification_dir = os.path.join(curr_dir, 'settings')
fpath_deepfaune_variables_json = os.path.join(curr_dir, 'models', 'deepfaune', 'variables.json')
admin_csv = os.path.join(curr_dir, "admin.csv")

# if the connection to gmail fails, it will retry with the following params
# retry *stop_max_attempt_number* times with an exponentially
# increasing wait time, starting from *wait_exponential_multiplier*
# milliseconds, up to a maximum of *wait_exponential_max* milliseconds
stop_max_attempt_number = 5
wait_exponential_multiplier = 1000
wait_exponential_max = 30000

# if the gmail connection could not be reset, the entire script will start again. 
script_refresh_max = 0 # I disabled this refresh because the retry from the run.py option does the same, but then better
script_refresh_multiplier = 4
script_refresh_start_sec = 10

#####################################
############ CREDENTIALS ############
#####################################

# set working directory to file location
import os
curr_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(curr_dir)

# read passwords from config.json
import json
with open("config.json", 'r') as f:
    config = json.load(f)

# check OS
if os.name == 'nt': # windows
    osys = "windows"
elif platform.system() == 'Darwin': # macos
    osys = "macos"
else: # linux
    osys = "linux"

# general
conda_dir_macos = config['conda_dir_macos']
conda_dir_linux = config['conda_dir_linux']
conda_dir_windows = config['conda_dir_windows']
conda_dir = conda_dir_windows if osys == "windows" else conda_dir_macos if osys == "macos" else conda_dir_linux
EcoAssist_files_macos = config['EcoAssist_files_macos']
EcoAssist_files_linux = config['EcoAssist_files_linux']
EcoAssist_files_windows = config['EcoAssist_files_windows']
EcoAssist_files = EcoAssist_files_windows if osys == "windows" else EcoAssist_files_macos if osys == "macos" else EcoAssist_files_linux
file_storage_dir_linux = config['file_storage_dir_linux']
url_prefix_macos = config['url_prefix_macos']
url_prefix_linux = config['url_prefix_linux']
url_prefix_windows = config['url_prefix_windows']
url_prefix = url_prefix_windows if osys == "windows" else url_prefix_macos if osys == "macos" else url_prefix_linux
save_images = config['save_images']
file_sharing_folder = config['file_sharing_folder']

# gmail 
gmail_label = config['gmail_label']
gmail_imap_server = config['gmail_imap_server']
gmail_username = config['gmail_username']
gmail_password = config['gmail_password']

# twilio
from twilio.rest import Client
twilio_account_sid = config['twilio_account_sid']
twilio_auth_token = config['twilio_auth_token']
twilio_messaging_service_ID = config['twilio_messaging_service_ID']
twilio_content_template_SID_macos = config['twilio_content_template_SID_macos']
twilio_content_template_SID_linux = config['twilio_content_template_SID_linux']
twilio_content_template_SID_windows = config['twilio_content_template_SID_windows']
twilio_content_template_SID = twilio_content_template_SID_windows if osys == "windows" else twilio_content_template_SID_macos if osys == "macos" else twilio_content_template_SID_linux
twilio_client = Client(twilio_account_sid, twilio_auth_token)

# mailgun
mailgun_messages_url = config['mailgun_messages_url']
mailgun_api_key = config['mailgun_api_key']

# imgbb
imgbb_key = config['imgbb_key']
use_imgbb = osys in ["windows", "macos"]

# add EcoAssist files to PATH
sys.path.insert(0, os.path.join(EcoAssist_files))

# add utils
from visualise_detection.bounding_box import bounding_box as bb


########################################
############ MAIN FUNCTIONS ############
########################################

# parse and combine project specific settings from xlsx files to dict
def import_project_settings():

    # init
    global all_project_settings
    all_project_settings = {}

    # loop over all project xslx files present
    for filename in [file for file in os.listdir(fpath_project_specification_dir) if file.endswith('.xlsx')]:

        # init
        project_name = os.path.splitext(filename)[0]
        log(f"parsing project settings for project '{project_name}'")

        # for project_xslx in 
        project_specification_xslx = os.path.join(fpath_project_specification_dir, filename)

        # import general settings
        general_settings_df = pd.read_excel(project_specification_xslx, sheet_name='general_settings')
        settings_dict = general_settings_df.set_index('key')['value'].to_dict()

        # add species presence bools
        species_presence_df = pd.read_excel(project_specification_xslx, sheet_name='species_presence')
        species_presence_dict = species_presence_df.set_index('class')['present'].to_dict()
        settings_dict["species_presence"] = species_presence_dict

        # read alias species names
        species_alias_dict = species_presence_df.set_index('class')['alias'].to_dict()
        settings_dict["species_alias"] = species_alias_dict

        # get list of camera IMEI numbers in use for this project
        cameras_in_use_df = pd.read_excel(project_specification_xslx, sheet_name='cameras_in_use')
        settings_dict["cameras_in_use"] = cameras_in_use_df['IMEI'].tolist()

        # format and add whatsapp receivers and preferences
        whatsapp_settings_df = pd.read_excel(project_specification_xslx, sheet_name='whatsapp_settings')
        whatsapp_settings_list = []
        for _, row in whatsapp_settings_df.iterrows():
            recipient_dict = row[['whatsapp_number', 'friendly_name']].to_dict()
            recipient_dict["selected_notifications"] = row.drop(['whatsapp_number', 'friendly_name']).to_dict()
            whatsapp_settings_list.append(recipient_dict)
        settings_dict["whatsapp_receivers"] = whatsapp_settings_list

        # format and add email receivers and preferences
        email_settings_df = pd.read_excel(project_specification_xslx, sheet_name='email_settings')
        email_settings_list = []
        for _, row in email_settings_df.iterrows():
            recipient_dict = row[['email_address', 'friendly_name']].to_dict()
            recipient_dict["selected_notifications"] = row.drop(['email_address', 'friendly_name']).to_dict()
            email_settings_list.append(recipient_dict)
        settings_dict["email_receivers"] = email_settings_list

        # format and add earthranger servers and preferences
        earthranger_settings_df = pd.read_excel(project_specification_xslx, sheet_name='earthranger_settings')
        earthranger_settings_list = []
        for _, row in earthranger_settings_df.iterrows():
            recipient_dict = row[['earthranger_post_server', 'friendly_name']].to_dict()
            recipient_dict["selected_notifications"] = row.drop(['earthranger_post_server', 'friendly_name']).to_dict()
            earthranger_settings_list.append(recipient_dict)
        settings_dict["earthranger_servers"] = earthranger_settings_list

        # add [project specific settings to main dict
        all_project_settings[project_name] = settings_dict
    
    # log
    log("project settings imported as:")
    log(json.dumps(all_project_settings, indent = 3))

# post-process files
# this is a simplified version of the ecoassist function
def postprocess(src_dir, dst_dir, thresh, sep, file_placement, sep_conf, vis, crp, exp, exp_format, data_type, time_elapsed = ""):

    # set json file
    recognition_file = os.path.join(src_dir, "image_recognition_file.json")

    # fetch label map from json
    def fetch_label_map_from_json(path_to_json):
        with open(path_to_json, "r") as json_file:
            data = json.load(json_file)
        label_map = data['detection_categories']
        return label_map
    label_map = fetch_label_map_from_json(recognition_file)
    inverted_label_map = {v: k for k, v in label_map.items()}

    # create list with colours for visualisation
    if vis:
        colors = ["fuchsia", "blue", "orange", "yellow", "green", "red", "aqua", "navy", "teal", "olive", "lime", "maroon", "purple"]
        colors = colors * 30
    
    # open json file
    with open(recognition_file) as image_recognition_file_content:
        data = json.load(image_recognition_file_content)
    n_images = len(data['images'])

    # initialise the csv files
    # csv files are always created, no matter what the user specified as export format
    # these csv files are then converted to the desired format and deleted, if required
    if exp:
        # for files
        csv_for_files = os.path.join(dst_dir, "results_files.csv")
        if not os.path.isfile(csv_for_files):
            df = pd.DataFrame(list(), columns=["absolute_path", "relative_path", "data_type", "n_detections", "max_confidence", "human_verified",
                                               'time_to_notification', # new column for EcoAssist-connect
                                               'DateTimeOriginal', 'DateTime', 'DateTimeDigitized', 'Latitude', 'Longitude', 'GPSLink', 'Altitude',
                                               'Make', 'Model', 'Flash', 'ExifOffset', 'ResolutionUnit', 'YCbCrPositioning', 'XResolution', 'YResolution',
                                               'ExifVersion', 'ComponentsConfiguration', 'FlashPixVersion', 'ColorSpace', 'ExifImageWidth',
                                               'ISOSpeedRatings', 'ExifImageHeight', 'ExposureMode', 'WhiteBalance', 'SceneCaptureType',
                                               'ExposureTime', 'Software', 'Sharpness', 'Saturation', 'ReferenceBlackWhite'])
            df.to_csv(csv_for_files, encoding='utf-8', index=False)
        
        # for detections
        csv_for_detections = os.path.join(dst_dir, "results_detections.csv")
        if not os.path.isfile(csv_for_detections):
            df = pd.DataFrame(list(), columns=["absolute_path", "relative_path", "data_type", "label", "confidence", "human_verified", "bbox_left",
                                               "bbox_top", "bbox_right", "bbox_bottom", "file_height", "file_width", 
                                               'time_to_notification', # new column for EcoAssist-connect
                                               'DateTimeOriginal', 'DateTime',
                                               'DateTimeDigitized', 'Latitude', 'Longitude', 'GPSLink', 'Altitude', 'Make', 'Model', 'Flash', 'ExifOffset',
                                               'ResolutionUnit', 'YCbCrPositioning', 'XResolution', 'YResolution', 'ExifVersion', 'ComponentsConfiguration',
                                               'FlashPixVersion', 'ColorSpace', 'ExifImageWidth', 'ISOSpeedRatings', 'ExifImageHeight', 'ExposureMode',
                                               'WhiteBalance', 'SceneCaptureType', 'ExposureTime', 'Software', 'Sharpness', 'Saturation', 'ReferenceBlackWhite'])
            df.to_csv(csv_for_detections, encoding='utf-8', index=False)

    # loop through images
    for image in data['images']:

        # check for failure
        if "failure" in image:
            log(f"MegaDetector could not process '{image['file']}' due to '{image['failure']}'", indent = 2)
            continue
        
        # get image info
        file = image['file']
        detections_list = image['detections']
        n_detections = len(detections_list)

        # init manually verify var (remnant of EcoAssist)
        manually_checked = False

        # init vars
        max_detection_conf = 0.0
        unique_labels = []
        bbox_info = []

        # open files
        if vis or crp or exp:
            if data_type == "img":
                im_to_vis = cv2.imread(os.path.normpath(os.path.join(src_dir, file)))

                # check if that image was able to be loaded
                if im_to_vis is None:
                    log(f"File '{image['file']}' was skipped by post processing features because vc2 could not import the image", indent = 2)
                    continue
                
                # load old image and extract EXIF
                origImage = Image.open(os.path.join(src_dir, file))
                try:
                    exif = origImage.info['exif']
                except:
                    exif = None
                origImage.close()

            # read image dates etc
            if exp:

                # try to read metadata
                try:
                    img_for_exif = PIL.Image.open(os.path.join(src_dir, file))
                    metadata = {
                        PIL.ExifTags.TAGS[k]: v
                        for k, v in img_for_exif._getexif().items()
                        if k in PIL.ExifTags.TAGS
                    }
                    img_for_exif.close()
                except:
                    metadata = {'GPSInfo': None,
                                 'ResolutionUnit': None,
                                 'ExifOffset': None,
                                 'Make': None,
                                 'Model': None,
                                 'DateTime': None,
                                 'YCbCrPositioning': None,
                                 'XResolution': None,
                                 'YResolution': None,
                                 'ExifVersion': None,
                                 'ComponentsConfiguration': None,
                                 'ShutterSpeedValue': None,
                                 'DateTimeOriginal': None,
                                 'DateTimeDigitized': None,
                                 'FlashPixVersion': None,
                                 'UserComment': None,
                                 'ColorSpace': None,
                                 'ExifImageWidth': None,
                                 'ExifImageHeight': None}

                # try to add GPS data
                try:
                    gpsinfo = gpsphoto.getGPSData(os.path.join(src_dir, file))
                    if 'Latitude' in gpsinfo and 'Longitude' in gpsinfo:
                        gpsinfo['GPSLink'] = f"https://maps.google.com/?q={gpsinfo['Latitude']},{gpsinfo['Longitude']}"
                except:
                    gpsinfo = {'Latitude': None,
                               'Longitude': None,
                               'GPSLink': None}
                
                # combine metadata and gps data
                exif_data = {**metadata, **gpsinfo} 

                # check if datetime values can be found
                exif_params = []
                for param in ['DateTimeOriginal', 'DateTime', 'DateTimeDigitized', 'Latitude', 'Longitude', 'GPSLink', 'Altitude', 'Make', 'Model',
                              'Flash', 'ExifOffset', 'ResolutionUnit', 'YCbCrPositioning', 'XResolution', 'YResolution', 'ExifVersion',
                              'ComponentsConfiguration', 'FlashPixVersion', 'ColorSpace', 'ExifImageWidth', 'ISOSpeedRatings',
                              'ExifImageHeight', 'ExposureMode', 'WhiteBalance', 'SceneCaptureType', 'ExposureTime', 'Software',
                              'Sharpness', 'Saturation', 'ReferenceBlackWhite']:
                    try:
                        if param.startswith('DateTime'):
                            datetime_raw = str(exif_data[param])
                            param_value = datetime.datetime.strptime(datetime_raw, '%Y:%m:%d %H:%M:%S').strftime('%d/%m/%y %H:%M:%S')
                        else:
                            param_value = str(exif_data[param])
                    except:
                        param_value = "NA"
                    exif_params.append(param_value)

        # loop through detections
        if 'detections' in image:
            for detection in image['detections']:

                # get confidence
                conf = detection["conf"]

                # write max conf
                if manually_checked:
                    max_detection_conf = "NA"
                elif conf > max_detection_conf:
                    max_detection_conf = conf

                # if above user specified thresh
                if conf >= thresh:

                    # change conf to string for verified images
                    if manually_checked:
                        conf = "NA"

                    # get detection info
                    category = detection["category"]
                    label = label_map[category]
                    if sep:
                        unique_labels.append(label)
                        unique_labels = sorted(list(set(unique_labels)))

                    # get bbox info
                    if vis or crp or exp:
                        if data_type == "img":
                            height, width = im_to_vis.shape[:2]
                        else:
                            height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            width = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))

                        w_box = detection['bbox'][2]
                        h_box = detection['bbox'][3]
                        xo = detection['bbox'][0] + (w_box/2)
                        yo = detection['bbox'][1] + (h_box/2)
                        left = int(round(detection['bbox'][0] * width))
                        top = int(round(detection['bbox'][1] * height))
                        right = int(round(w_box * width)) + left
                        bottom = int(round(h_box * height)) + top

                        # store in list
                        bbox_info.append([label, conf, manually_checked, left, top, right, bottom, height, width, xo, yo, w_box, h_box])

        # separate files
        if sep:
            if n_detections == 0:
                file = move_files(file, "empty", file_placement, max_detection_conf, sep_conf, dst_dir, src_dir, manually_checked)
            else:
                if len(unique_labels) > 1:
                    labels_str = "_".join(unique_labels)
                    file = move_files(file, labels_str, file_placement, max_detection_conf, sep_conf, dst_dir, src_dir, manually_checked)
                elif len(unique_labels) == 0:
                    file = move_files(file, "empty", file_placement, max_detection_conf, sep_conf, dst_dir, src_dir, manually_checked)
                else:
                    file = move_files(file, label, file_placement, max_detection_conf, sep_conf, dst_dir, src_dir, manually_checked)
        
        # collect info to append to csv files
        if exp:
            # file info
            row = pd.DataFrame([[src_dir, file, data_type, len(bbox_info), max_detection_conf, manually_checked, time_elapsed, *exif_params]])
            row.to_csv(csv_for_files, encoding='utf-8', mode='a', index=False, header=False)

            # detections info
            rows = []
            for bbox in bbox_info:
                row = [src_dir, file, data_type, *bbox[:9], time_elapsed, *exif_params]
                rows.append(row)
            rows = pd.DataFrame(rows)
            rows.to_csv(csv_for_detections, encoding='utf-8', mode='a', index=False, header=False)
    
        # visualize images
        if vis and len(bbox_info) > 0:
            for bbox in bbox_info:
                if manually_checked:
                    vis_label = f"{bbox[0]} (verified)"
                else:
                    vis_label = f"{bbox[0]} {round(bbox[1], 2)}"
                color = colors[int(inverted_label_map[bbox[0]])]
                bb.add(im_to_vis, *bbox[3:7], vis_label, color)
            im = os.path.join(dst_dir, file)
            Path(os.path.dirname(im)).mkdir(parents=True, exist_ok=True)
            cv2.imwrite(im, im_to_vis)

            # load new image and save exif
            if (exif != None):
                image_new = Image.open(im)
                image_new.save(im, exif=exif)
                image_new.close()

    # create summary csv
    if exp:
        csv_for_summary = os.path.join(dst_dir, "results_summary.csv")
        if os.path.exists(csv_for_summary):
            os.remove(csv_for_summary)
        det_info = pd.DataFrame(pd.read_csv(csv_for_detections, dtype=dtypes, low_memory=False))
        summary = pd.DataFrame(det_info.groupby(['label', 'data_type']).size().sort_values(ascending=False).reset_index(name='n_detections'))
        summary.to_csv(csv_for_summary, encoding='utf-8', mode='w', index=False, header=True)

# blur specific bbox
def blur_box(image_path, width, height, bbox):
    image = cv2.imread(image_path)
    x = int(bbox[0] * width)
    y = int(bbox[1] * height)
    w = int(bbox[2] * width)
    h = int(bbox[3] * height)
    roi = image[y:y+h, x:x+w]
    blurred_roi = cv2.GaussianBlur(roi, (71, 71), 0)
    image[y:y+h, x:x+w] = blurred_roi
    cv2.imwrite(image_path, image)
    log(f"blurred image saved", indent = 2)

# predict on single image
def predict_single_image(filename, full_path_org, full_path_vis, camera_id, project_name):
    log(f"running inference", indent = 2)

    # get project specific thresholds
    postprocess_threshold = all_project_settings[project_name]["postprocess_threshold"]
    detection_threshold = all_project_settings[project_name]["detection_threshold"]
    classification_threshold = all_project_settings[project_name]["classification_threshold"]

    # get species alias names
    species_alias = all_project_settings[project_name]["species_alias"]

    # get project preferences
    blur_people_bool = all_project_settings[project_name].get("blur_people", True)

    # make sure only the project specific species can be predicted
    update_species_presence_json(project_name) 
    
    # init vars
    img_dir = os.path.dirname(full_path_org)
    Path(os.path.dirname(full_path_vis)).mkdir(parents=True, exist_ok=True)

    # run megadetector
    log("running megadetector", indent = 2)
    md_cmd_windows = [f'{curr_dir}/run_megadetector.bat', str(curr_dir), str(conda_dir), str(detection_threshold), str(EcoAssist_files), str(img_dir)]
    md_cmd_unix = ['bash', f'{curr_dir}/run_megadetector.command', str(curr_dir), str(conda_dir), str(detection_threshold), str(EcoAssist_files), str(img_dir)]
    run_bash_cmd(md_cmd_windows if osys == "windows" else md_cmd_unix)

    # run deepfaune 
    log("running deepfaune", indent = 2)
    df_cmd_windows = [f'{curr_dir}/run_deepfaune.bat', str(curr_dir), str(conda_dir), str(classification_threshold), str(EcoAssist_files), str(img_dir)]
    df_cmd_unix = ['bash', f'{curr_dir}/run_deepfaune.command', str(curr_dir), str(conda_dir), str(classification_threshold), str(EcoAssist_files), str(img_dir)]
    run_bash_cmd(df_cmd_windows if osys == "windows" else df_cmd_unix)

    # loop through json
    json_fpath = os.path.join(img_dir, "image_recognition_file.json")
    with open(json_fpath) as image_recognition_file_content:
        data = json.load(image_recognition_file_content)
    label_map = data['detection_categories']
    for image in data['images']:
        if "failure" in image:
            log(f"MegaDetector could not process '{image['file']}' due to '{image['failure']}'", indent = 2)
            continue
        detections_dict = {}
        if 'detections' in image:
            for detection in image['detections']:
                det_label_original = label_map.get(detection['category'], "unknown")  # the original label
                det_label = species_alias.get(det_label_original, det_label_original) # the set alias for this species
                value = {"conf" : detection['conf'], "bbox" : detection['bbox']}
                add_detection(detections_dict, det_label, value)

    # if nothing is detected add dummy detection so that people can receive a notification if required
    if detections_dict == {}:
        log(f"detected no objects labelled as empty image", indent = 2)
        det_label_original = "empty"
        detections_dict["empty"] = [{'conf': 0, 'bbox': [0, 0, 0, 0]}]
    
    # image specific metadata
    exif = fetch_img_exif(full_path_org)
    gps = fetch_lat_lon(full_path_org)
    PIL_image = Image.open(full_path_org)
    img_width, img_height = PIL_image.size

    # blur people
    if blur_people_bool:
        if "person" in detections_dict:
            for person_info in detections_dict["person"]:
                if person_info["conf"] >= postprocess_threshold:
                    log(f"blurring person bbox", indent = 2)
                    blur_box(full_path_org, img_width, img_height, person_info["bbox"])

    # detection specifc information
    for label, detections in detections_dict.items():
        count = len(detections)
        max_conf = max(item['conf'] for item in detections)
        log(f"detected {int(count)} {label} with max conf {max_conf}", indent = 2)

        # visualize
        log(f"visualising image", indent = 3)
        image_to_vis = cv2.imread(full_path_org)
        for detection in detections:
            left = int(round(detection['bbox'][0] * img_width))
            top = int(round(detection['bbox'][1] * img_height))
            right = int(round(detection['bbox'][2] * img_width)) + left
            bottom = int(round(detection['bbox'][3] * img_height)) + top
            bb.add(image_to_vis, left, top, right, bottom, f'{label} {detection["conf"]}', "red")
        cv2.imwrite(full_path_vis, image_to_vis)
        log(f"saved visualised image to {full_path_vis}", indent = 3)
        
        # structure payload
        detection_payload = {
            "camera_trap_name" : camera_id,
            "longitude" : gps.get('Longitude', 0.0),
            "latitude" : gps.get('Latitude', 0.0),
            "timestamp" : exif.get('DateTimeOriginal', "unknown"),
            "media_name" : filename,
            "type" : "image/jpeg",
            "size" : os.path.getsize(full_path_vis),
            "summary" : "Generated by EcoAssist - https://addaxdatascience.com/ecoassist/ ",
            "image" : convert_to_base64(full_path_vis),
            "camera_make" : exif.get('Make', "unknown"),
            "camera_model" : exif.get('Model', "unknown"),
            "original_label": det_label_original,
            "detection" : label,
            "project_name" : project_name,
            "detection_number" : int(count),
            "max_det_conf" : max_conf,
            "gps_link" : "" if gps.get('Latitude', 0.0) == 0. and gps.get('Longitude', 0.0) == 0. else f"maps.google.com/?q={gps.get('Latitude', 0.0)},{gps.get('Longitude', 0.0)}",
            "cls_model_name" : "Deepfaune v1.1",
            "det_model_name" : "MegaDetector v5a",
        }

        # add time elapsed to detection payload
        detection_payload["time_elapsed"] = calc_sec_elapsed(detection_payload["timestamp"])

        # log all keys except the image base64 string
        log("detection_payload printed below", indent = 3)
        for k, v in detection_payload.items():
            if k != "image":
                log(f"{k} : {v}", indent = 4)
    
        # send detection to whatsapp numbers
        if all_project_settings[project_name]["whatsapp_receivers"]:
            log(f"initiating whatsapp service", indent = 3)
            send_whatsapp(detection_payload, full_path_vis, full_path_org)
        
        # send email
        if all_project_settings[project_name]["email_receivers"]:

            # get a list of email receivers
            email_receivers = []
            for receiver_info in all_project_settings[project_name]["email_receivers"]:
                email_address = receiver_info['email_address']
                friendly_name = receiver_info['friendly_name']

            # check if this receiver wants to get notified on this detection
            if receiver_info['selected_notifications'][str(detection_payload["detection"])]:
                log(f"{friendly_name} ({email_address}) does want to get notified for class '{detection_payload['detection']}'", indent=3)
                email_receivers.append([email_address, friendly_name])
            else:
                log(f"{friendly_name} ({email_address}) does not want to get notified for class '{detection_payload['detection']}'", indent=3)

            # send emails   
            for email_address, friendly_name in email_receivers:
                log(f"initiating email service", indent = 3)
                try:
                    send_email_plain(email_address, friendly_name, detection_payload)
                    # send_email_html(receiver_email, detection_payload) # doesn't render properly in gmail
                except Exception as e:
                    log(f"could not send email because '{e}'", indent = 3)
                    log("skipping email notification", indent = 3)

        # push detection to earthranger
        if all_project_settings[project_name]["earthranger_servers"]:
            log("initiating earthranger push", indent = 3)
            for server_info in all_project_settings[project_name]["earthranger_servers"]:
                earthranger_post_server = server_info["earthranger_post_server"]
                earthranger_friendly_name = server_info["friendly_name"]
                if server_info['selected_notifications'][str(detection_payload["detection"])]:  
                    log(f"{earthranger_friendly_name} ({earthranger_post_server}) does want to get pushed for class '{detection_payload['detection']}'", indent=3)                  
                    log(f"uploading payload to {earthranger_post_server}", indent = 3)
                    response = requests.post(earthranger_post_server, data=json.dumps(detection_payload), headers={'Content-Type': 'application/json'})
                    if response.status_code == 200:
                        log(f"payload successfully uploaded to {earthranger_post_server}", indent = 3)
                    else:
                        log(f"error when uploading to {earthranger_post_server}", indent = 3)
                        log(response.text)
                else:
                    log(f"{earthranger_friendly_name} ({earthranger_post_server}) does not want to get pushed for class '{detection_payload['detection']}'", indent=3)
    
    # save observations to in CSVs
    dst_dir = os.path.join(fpath_output_dir, project_name)
    Path(dst_dir).mkdir(parents=True, exist_ok=True)
    postprocess(src_dir = img_dir, 
                dst_dir = dst_dir,
                thresh = postprocess_threshold,
                sep = False,
                file_placement = 2,
                sep_conf = False,
                vis = False,
                crp = False,
                exp = True,
                exp_format = "CSV",
                data_type = "img",
                time_elapsed = detection_payload["time_elapsed"])
    
    if save_images:
        # save the visualised images
        dst_dir = os.path.join(fpath_output_dir, project_name, "saved_imgs", "vis")
        Path(dst_dir).mkdir(parents=True, exist_ok=True)
        postprocess(src_dir = img_dir,
                    dst_dir = dst_dir,
                    thresh = postprocess_threshold,
                    sep = True,
                    file_placement = 2,
                    sep_conf = False,
                    vis = True,
                    crp = False,
                    exp = False,
                    exp_format = "CSV",
                    data_type = "img")

        # save the original images
        dst_dir = os.path.join(fpath_output_dir, project_name, "saved_imgs", "org")
        Path(dst_dir).mkdir(parents=True, exist_ok=True)
        postprocess(src_dir = img_dir,
                    dst_dir = dst_dir,
                    thresh = postprocess_threshold,
                    sep = True,
                    file_placement = 2,
                    sep_conf = False,
                    vis = False,
                    crp = False,
                    exp = False,
                    exp_format = "CSV",
                    data_type = "img")

    return True

# # refresh folder and remove temporary files # DEBUG depreciated
# def remove_temp_files():
#     temp_dirs = ['vis', 'org']
#     for temp_dir in temp_dirs:
#         root_dir = os.path.join(curr_dir, 'temp', temp_dir)
#         files = os.listdir(root_dir)
#         for file in files:
#             file_path = os.path.join(root_dir, file)
#             if os.path.isfile(file_path):
#                 os.remove(file_path)
#                 log(f"removed temporary file {file_path}", indent = 2)

# find out to which project the camera belongs to
def retrieve_project_name_from_imei(input_imei):
    for project_name, project_settings in all_project_settings.items():
        if int(input_imei) in project_settings["cameras_in_use"] or \
            str(input_imei) in project_settings["cameras_in_use"]:
            log(f"found imei '{input_imei}' listed under project '{project_name}'", indent = 2)
            return project_name

# convert image from base64
# def convert_from_base64(base64_string):
#     return base64.b64decode(base64_string)

# gmail checker with retry functionality
class IMAPConnection():
    
    # set init functions
    def __init__(self):
        self.imap = imaplib.IMAP4_SSL(gmail_imap_server, 993)
        
    def login(self):
        self.imap.login(gmail_username, gmail_password)
        
    def logout(self):
        self.imap.logout()

    # check for incoming emails from the camera trap
    @retrying.retry(stop_max_attempt_number=stop_max_attempt_number, wait_exponential_multiplier=wait_exponential_multiplier, wait_exponential_max=wait_exponential_max)
    # retry *stop_max_attempt_number* times with an exponentially increasing wait time, starting from *wait_exponential_multiplier* milliseconds, up to a maximum of *wait_exponential_max* milliseconds
    def check_tasks(self):
        try:
            log("checking email")
            self.imap.select(gmail_label)
            status, messages = self.imap.search(None, '(UNSEEN)')
            if status == "OK":
                message_ids = messages[0].split()
                if message_ids:
                    # loop through all unread emails
                    log(f"found {len(message_ids)} new email(s)", indent=1, new_line=True)
                    for i, msg_id in enumerate(message_ids):

                        # read email
                        log(f"reading email number {i+1}", indent=1)
                        _, msg_data = self.imap.fetch(msg_id, "(RFC822)")
                        raw_email = msg_data[0][1]
                        email_message = email.message_from_bytes(raw_email)
                        filename = decode_subject(email_message["Subject"])
                        attachement = fetch_attachment(email_message)

                        # find out which project it is
                        imei_number = filename.split("-", 1)[0]
                        if imei_number == 'VELUWE HANS ': # DEBUG TODO: dit even snel gedaan omdat de nieuwe camera's niet de IMEI in de filename doen. Even uitzoeken hoe we dit willen doen. Misschien dan toch maar srteren op camID? 
                            imei_number = '860946062360345'
                        project_name = retrieve_project_name_from_imei(imei_number)
                        if project_name is None:
                            log(f"could not retrieve project name from imei number '{imei_number}'", indent=2)
                            return

                        # find camera id from email body
                        # TODO: hier moet de datetime uitgelezen worden
                        body = ""
                        if email_message.is_multipart():
                            for part in email_message.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                if "text" in content_type and "attachment" not in content_disposition:
                                    body = part.get_payload(decode=True).decode().split('\n')[0]
                                    break
                        else:
                            body = email_message.get_payload(decode=True).decode().split('\n')[0]
                        camera_id = body.replace("Camera ID: ", "").strip()
                        log(f"found camera ID from email body '{camera_id}'", indent=2)
                        camera_id = remove_trailing_zeros(camera_id)
                        log(f"cleaned camera ID to '{camera_id}'", indent=2)

                        # save attachment locally
                        log(f"extracted {filename} from email", indent=2)
                        img_id = get_img_id()
                        if filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
                            exif_data = attachement.info.get('exif')
                            filename = filename.replace(" ", "_")
                            fpath_org_img = os.path.join(curr_dir, 'imgs', img_id, 'org', filename)
                            fpath_vis_img = os.path.join(curr_dir, 'imgs', img_id, 'vis', filename)
                            
                            Path(os.path.dirname(fpath_org_img)).mkdir(parents=True, exist_ok=True)
                            if exif_data is not None:
                                log(f"saved image to {fpath_org_img} with exif data", indent=2)
                                attachement.save(fpath_org_img, exif=exif_data)
                            else:
                                log(f"saved image to {fpath_org_img} without exif data", indent=2)
                                attachement.save(fpath_org_img)
                            
                            # check if image size is small
                            with Image.open(fpath_org_img) as image2G:
                                width, height =image2G.size
                                if width == 640 and height == 480:
                                    log("image size is small - camera send image with 2G connection", indent = 2)   
                                    
                                    # adding current datetime
                                    # TODO: dit moet uit de email body
                                    log("adding current datetime as temporary solution", indent = 2)
                                    current_datetime = datetime.datetime.now().strftime('%Y:%m:%d %H:%M:%S')
                                    exif_dict = piexif.load(image2G.info['exif']) if 'exif' in image2G.info else {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                                    exif_dict['0th'][piexif.ImageIFD.DateTime] = current_datetime
                                    exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = current_datetime
                                    exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = current_datetime
                                    exif_bytes = piexif.dump(exif_dict)

                                    # replace original image with exif image
                                    image2G.save(fpath_org_img, "jpeg", exif=exif_bytes)   
                            
                            # add row to CSV file
                            img_id_suffix_org = "<NA>" if use_imgbb else os.sep.join(fpath_org_img.split(os.sep)[-3:])
                            img_id_suffix_vis = "<NA>" if use_imgbb else os.sep.join(fpath_vis_img.split(os.sep)[-3:])
                            update_admin_csv({'img_id': img_id,
                                              'full_path_org': fpath_org_img,
                                              'full_path_vis': fpath_vis_img,
                                              'url_org': f"{url_prefix}{img_id_suffix_org}",
                                              'url_vis': f"{url_prefix}{img_id_suffix_vis}",
                                              'filename': filename,
                                              'project_name': project_name,
                                              'camera_id': camera_id,
                                              'analysed': False,
                                              'inference_retry_count': 0})

                        # attachment is not an image
                        else:
                            log(f"did not run inference because {filename} is not JPG", indent=2)
                            if "DailyReport" in filename:
                                log(f"found daily report", indent=2)
                                daily_report_dict = parse_txt_file(attachement)
                                log(f"parsed daily report as", indent=2)
                                for k, v in daily_report_dict.items():
                                    log(f"{k} : {v}", indent = 3)
                                add_dict_to_csv(daily_report_dict, fpath_daily_report_csv)
                                # TODO: add to daily report CSV

        # retry if something blocks the connection
        except Exception as e:
            log(f"an error occurred. Retrying connection...")
            log(f"\n\nerror: {e}")
            log(f"traceback: {traceback.print_exc()}\n\n")
            raise
        
        # loop thourgh csv and check which images need to be analysed
        with open(admin_csv, 'r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                if row['analysed'] == 'False':
                    log(f"analysing image: {img_id}", new_line = True)
                    img_id = row['img_id']
                    full_path_org = row['full_path_org']
                    full_path_vis = row['full_path_vis']
                    filename = row['filename']
                    camera_id = row['camera_id']
                    project_name = row['project_name']
                    inference_retry_count = int(row['inference_retry_count'])
                    
                    try:
                        if inference_retry_count <= 3:
                            log(f"running inference on image '{filename}'", indent = 2)
                            predict_bool = predict_single_image(filename, full_path_org, full_path_vis, camera_id, project_name)
                            if predict_bool:
                                update_admin_csv({'img_id': img_id,
                                                'analysed': True})
                    except Exception as e:
                        log(f"an error occurred. Could not run inference on image '{filename}' because '{e}'", indent = 2)
                        log(f"traceback: {traceback.print_exc()}", indent = 2)
                        inference_retry_count = inference_retry_count + 1
                        update_admin_csv({'img_id': img_id,
                                          'inference_retry_count': inference_retry_count})
                        if inference_retry_count > 3:
                            log(f"maximum retries exceeded. Skipping image '{filename}'", indent = 2)
                            update_admin_csv({'img_id': img_id,
                                              'analysed': True})

# get unique string
def get_img_id():
    return str(datetime.datetime.now().strftime('%Y%m%d') + "-" + str(uuid.uuid4())[:5])

# send whatsapp message
def send_whatsapp(detection_payload, full_path_vis, full_path_org):
    
    # upload image to imgbb
    if use_imgbb:

        # the image must be from url, so upload to imgBB gets automatically removed after five minutes
        url = "https://api.imgbb.com/1/upload"
        imgbb_payload = {
            "key": imgbb_key,
            "image": detection_payload["image"]
        }
        res = requests.post(url, imgbb_payload)
        upload_report = res.json()
        log("uploaded to imgbb", indent = 3)
    
        # check if it worked
        success = upload_report.get("success", False)
        if not success:
            print("failed to upload. No whatsapp img. Send without image.") # TODO: iets van een notificatie sturen oid? Wat is de error code?
        else:
            img_id_suffix = upload_report["data"]["url"].replace('https://i.ibb.co/', '')
            log(f"retrieved img url suffix {img_id_suffix}", indent = 3)
    
    # on ubuntu server we don't need imgBB but will place the img in the file server
    else:
        
        # move both the original and the visualised image to the file server
        for src in [full_path_org, full_path_vis]:
            img_id_suffix = os.sep.join(src.split(os.sep)[-3:])
            dst = os.path.join(file_sharing_folder, img_id_suffix)
            dst_dir = os.path.dirname(dst)
            if not os.path.exists(dst_dir):
                subprocess.run(['sudo', 'mkdir', '-p', dst_dir], check=True)
            subprocess.run(['sudo', 'cp', src, dst], check=True)
            log(f"copied '{src}' to '{dst}'", indent = 3)

    # set vars to be passed on to the whatsapp template
    # https://console.twilio.com/us1/develop/sms/content-template-builder
    content_vars = json.dumps({
        '1': str(detection_payload["detection"].capitalize()), # object observed
        '2': str(detection_payload["time_elapsed"]), # time elapsed
        '3': str(detection_payload["camera_trap_name"]), # camera ID
        '4': str(sep_date_time(detection_payload["timestamp"])[1]), # time string
        '5': str(sep_date_time(detection_payload["timestamp"])[0]), # date string
        '6': "GPS not set" if detection_payload["gps_link"] == "" else str(detection_payload["gps_link"]), # location url
        '7': img_id_suffix # img url suffix to be placed behind the base url
        })
              
    # get a list of whatsapp receivers
    whatsapp_receivers = []
    for receiver_info in all_project_settings[detection_payload["project_name"]]["whatsapp_receivers"]:
        number = f"+{receiver_info['whatsapp_number']}"
        friendly_name = receiver_info['friendly_name']

        # check if this receiver wants to get notified on this detection
        if receiver_info['selected_notifications'][str(detection_payload["original_label"])]:
            log(f"{friendly_name} ({number}) does want to get notified for class '{detection_payload['detection']}'", indent=3)
            whatsapp_receivers.append([number, friendly_name])
        else:
            log(f"{friendly_name} ({number}) does not want to get notified for class '{detection_payload['detection']}'", indent=3)

    # call the twilio function with retry logic
    try:
        send_whatsapp_via_twilio(content_vars, whatsapp_receivers)
    except retrying.RetryError:
        log("maximum retries exceeded. Could not send WhatsApp message.", indent=3)

# have a separate function so that we can use the retry mechanism to use twilio API
@retrying.retry(stop_max_attempt_number=stop_max_attempt_number, wait_exponential_multiplier=wait_exponential_multiplier, wait_exponential_max=wait_exponential_max)  
# retry *stop_max_attempt_number* times with an exponentially increasing wait time, starting from *wait_exponential_multiplier* milliseconds, up to a maximum of *wait_exponential_max* milliseconds
def send_whatsapp_via_twilio(content_vars, whatsapp_receivers):
    try:
        for number, friendly_name in whatsapp_receivers:
            message = twilio_client.messages.create(
                content_sid=twilio_content_template_SID,
                from_=twilio_messaging_service_ID,
                content_variables=content_vars,
                to=f'whatsapp:{number}'
            )
            log(f"whatsapp message sent to {friendly_name} ({number}) with ID {message.sid}", indent=3)
    except TwilioException as e:
        log(f"twilio error occurred: {str(e)}", indent=3)
        raise

# send email to one recipient
def send_email_html(receiver_email, detection_payload):
    
    # do not call this function since the html code does not render well in mailgun gmail
    log("email manually blocked from sending", indent = 2)
    return

    # init email
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message['Message-ID'] = make_msgid()
    message["Subject"] = f'Camera trap alert: {detection_payload["detection"].capitalize()} observed!\n'

    # fill email with html content
    border_size = 0
    total_table_width = 400
    
    def add_html_row_2col(key, value):
        return f"<tr><td style='width: 50%; text-align: right; font-weight: bold; padding: 0px 5px;'>{key}</td><td style='width: 50%; padding: 0px 5px;'>{value}</td></tr>\n"
        
    def add_html_row_1col(text):
        return f"<table border='{border_size}' style='font-family: \"PT Sans\", sans-serif; width: {total_table_width}px;'><tr><td colspan='3' style='text-align: center;'>{text}</td></tr></table>"
    
    def add_empty_html_row():
        return "<tr><td colspan='2'>&nbsp;</td></tr>\n"
    
    def add_html_logo(base64_file_path, target_url):
        with open(base64_file_path, 'r') as f:
            image_base64 = f.read().strip()
        return f"<td style='width: {total_table_width/3}px; text-align: center;'><a href='{target_url}' target='_blank'><img src='data:image/png;base64,{image_base64}' style='max-height: {(total_table_width/3)/2}px;'></a></td>"

    def add_html_img(image_base64):
        html = f"<table border='{border_size}' style='font-family: \"PT Sans\", sans-serif; width: {total_table_width}px;'><tr>"
        html += f"<td style='text-align: center;'><img src='data:image/png;base64,{image_base64}' style='max-width: {total_table_width - 30}px;'></a></td>"
        html += "</tr></table>"
        return html

    # concat string
    html_string = ""
    html_string += add_html_img(detection_payload['image'])
    html_string += f"<table border='{border_size}' style='font-family: \"PT Sans\", sans-serif; width: {total_table_width}px;'>\n"
    html_string += add_html_row_2col("Observation", detection_payload['detection'].capitalize())
    html_string += add_html_row_2col("Confidence", detection_payload['max_det_conf'])
    html_string += add_html_row_2col("Count", detection_payload['detection_number'])
    html_string += add_html_row_2col("Timestamp", detection_payload['timestamp'])
    html_string += add_html_row_2col("Camera ID", detection_payload['camera_trap_name'])
    if detection_payload['latitude'] == 0. and detection_payload['longitude'] == 0.:
        html_string += add_html_row_2col("Location", "Unknown - GPS not set")
    else:
        html_string += add_html_row_2col("Latitude", detection_payload['latitude'])
        html_string += add_html_row_2col("Longitude", detection_payload['longitude'])
        html_string += add_html_row_2col("Location link", f"<a href='{detection_payload['gps_link']}'>Google Maps</a>")
    html_string += add_html_row_2col("Detection model", detection_payload['det_model_name'])
    html_string += add_html_row_2col("Identification model", detection_payload['model_name'])
    html_string += "</table>"
    html_string += add_empty_html_row()
    html_string += add_html_row_1col("<em>Generated by <a href='https://addaxdatascience.com/ecoassist/'>EcoAssist</a>.</em>")
    html_string += f"<table border='{border_size}' style='font-family: \"PT Sans\", sans-serif; width: {total_table_width}px;'><tr>"
    html_string += add_html_logo(os.path.join("logos", "ecoassist.txt"), "https://addaxdatascience.com/ecoassist/")
    html_string += add_html_logo(os.path.join("logos", "smartparks.txt"), "https://www.smartparks.org/")
    html_string += add_html_logo(os.path.join("logos", "addax.txt"), "https://addaxdatascience.com/")
    html_string += "</tr></table>"
    message.attach(MIMEText(html_string, "html"))

    with open("email.html", "w") as file:
        file.write(html_string)
    with open("email.html", "r") as file:
        html_content_read = file.read()

    send_complex_message(html_content_read)
    return

    # log in and send
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(outgoing_server, port, context=context) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, "This is an automated email to notify you of a camera trap observation.")

def send_mailgun_email(receiver, subject, text):
    return requests.post(
        mailgun_messages_url,
        auth=("api", mailgun_api_key),
        files=[("attachment", open(fpath_vis_img, 'rb').read())],
        data={"from": "EcoAssist <mailgun@sandbox3a89d8176e8042f5a3f1c359ec1e86a7.mailgun.org>",
              "to": receiver,
              "subject": subject,
              "text": f"{text}"})

def send_email_plain(email_address, friendly_name, detection_payload):
    
    # fill plain text
    plain_string = ""
    plain_string += f"Hi {friendly_name}\n"
    plain_string += "This is an automated email to notify you of a camera trap observation.\n"
    plain_string += "\n"
    plain_string += f"Observation : {detection_payload['detection']}\n"
    plain_string += f"Confidence : {detection_payload['max_det_conf']}\n"
    plain_string += f"Count : {detection_payload['detection_number']}\n"
    plain_string += f"Timestamp : {detection_payload['timestamp']}\n"
    plain_string += f"Camera ID : {detection_payload['camera_trap_name']}\n"
    if detection_payload['latitude'] == 0. and detection_payload['longitude'] == 0.:
        plain_string += f"Location : Unknown - GPS not set\n"
    else:
        plain_string += f"Latitude : {detection_payload['latitude']}\n"
        plain_string += f"Longitude : {detection_payload['longitude']}\n"
        plain_string += f"Location link : {detection_payload['gps_link']}\n"
    plain_string += f"Detection model : {detection_payload['det_model_name']}\n"
    plain_string += f"Identification model : {detection_payload['cls_model_name']}\n"
    plain_string += "\n"
    plain_string += "Generated by EcoAssist-connect - https://addaxdatascience.com/ecoassist/\n"
    plain_string += "Don't want to receive these emails anymore? Let us known by sending an email to peter@addaxdatascience.com\n"
    
    # try to send email with plain text and image attachement
    try:
        response = requests.post(
            "https://api.mailgun.net/v3/sandbox3a89d8176e8042f5a3f1c359ec1e86a7.mailgun.org/messages",
            auth=("api", "7d4b1020fa652417a546393991c87803-19806d14-aec462f8"),
            files=[("attachment", open(fpath_vis_img, 'rb').read())],
            data={"from": "EcoAssist <mailgun@sandbox3a89d8176e8042f5a3f1c359ec1e86a7.mailgun.org>",
                "to": email_address,
                "subject": f'Camera trap alert: {detection_payload["detection"].capitalize()} observed!',
                "text": f"{plain_string}"})
        if response.status_code == 200:
            log(f"email sent successfully to {friendly_name} ({email_address})", indent = 2)
        else:
            log(f"failed to send email with status code {response.status_code}", indent = 2)
    except Exception as e:
        log(f"failed to send email {str(e)}")

# this function updates the selected species presence to JSON to mimic the use of EcoAssist
def update_species_presence_json(project_name):

    # get project specific species presence list
    species_presence_list = [key for key, value in all_project_settings[project_name]["species_presence"].items() if value]

    # read json
    with open(fpath_deepfaune_variables_json, 'r') as file:
        data = json.load(file)

    # adjust
    data['selected_classes'] = species_presence_list

    # write back
    with open(fpath_deepfaune_variables_json, 'w') as file:
        json.dump(data, file, indent=2)

##########################################
############ HELPER FUNCTIONS ############
##########################################

# run bash command and log output
def run_bash_cmd(cmd_list):
    p = Popen(cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                shell=False,
                universal_newlines=True)
    for line in p.stdout: 
        # continue
        if "MPS backend" not in line and \
            "vit_large_patch14_dinov2.lvd142m" not in line:
            log(line, indent = 3, end = '')

# read daily report
def parse_txt_file(file):
    parsed_data = {}
    lines = file.strip().splitlines()

    # read 
    try:
        for line in lines:
            line = line.strip()
            if line:
                if ":" in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    parsed_data[key] = value
    except FileNotFoundError:
        print(f"Error: File '{file}' not found.")
    except Exception as e:
        print(f"Error: {e}")
    
    # format signal percentage
    try: 
        signal_percentage = round((int(parsed_data["CSQ"]) / 31) * 100, 1)
    except Exception as e:
        log(f"could not parse signal percentage: {e}")
        signal_percentage = "Unknown"
    parsed_data["signal_percentage"] = signal_percentage

    # format camera name
    try: 
        cam_name = remove_trailing_zeros(parsed_data["CamID"])
    except Exception as e:
        log(f"could not parse camera name: {e}")
        cam_name = "Unknown"
    parsed_data["camera_name"] = cam_name

    # format temperature
    try: 
        temperature = float(parsed_data["Temp"].replace(" Celsius Degree", ""))
    except Exception as e:
        log(f"could not parse temperature: {e}")
        temperature = "Unknown"
    parsed_data["temperature"] = temperature

    # format date
    try:
        report_datetime = datetime.datetime.strptime(parsed_data["Date"], "%d/%m/%Y %H:%M:%S")
    except Exception as e:
        log(f"could not parse date: {e}")
        report_datetime = "Unknown"
    parsed_data["report_datetime"] = str(report_datetime)

    # format battery percentage
    try:
        battery_percentage = float(parsed_data["Battery"].replace("%", ""))
    except Exception as e:
        log(f"could not parse battery percentage: {e}")
        battery_percentage = "Unknown"
    parsed_data["battery_percentage"] = battery_percentage

    # format SD filled and SD total
    try:
        sd_full, sd_total = parsed_data["SD"].split("/")
        sd_percentage_free = round((float(re.sub(r'\D', '', sd_full)) / float(re.sub(r'\D', '', sd_total))) * 100, 1)
    except Exception as e:
        log(f"could not parse SD information: {e}")
        sd_full = "Unknown"
        sd_total = "Unknown"
        sd_percentage_free = "Unknown"
    parsed_data["sd_full"] = str(sd_full)
    parsed_data["sd_total"] = str(sd_total)
    parsed_data["sd_percentage_free"] = sd_percentage_free

    # format lat lon link
    try:
        gps_lat, gps_lon = read_gps_from_text(parsed_data["GPS"])
        gps_link = "Unknown" if gps_lat == 0. and gps_lon == 0. else f"maps.google.com/?q={gps_lat},{gps_lon}"
    except Exception as e:
        log(f"could not parse lat lon link: {e}")
        gps_lat = "Unknown"
        gps_lon = "Unknown"
        gps_link = "Unknown"
    parsed_data["gps_lat"] = str(gps_lat)
    parsed_data["gps_lon"] = str(gps_lon)
    parsed_data["gps_link"] = str(gps_link)

    # return
    return parsed_data

# append dict to csv file
def add_dict_to_csv(data_dict, csv_file_path):
    headers = list(data_dict.keys())
    file_exists = os.path.isfile(csv_file_path)
    with open(csv_file_path, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerow(data_dict)

# log to file and to console
def log(string, indent = 0, end = '\n', new_line = False):
    timestamp = datetime.datetime.now().replace(microsecond=0)
    indent_str = '    ' * indent
    new_line_str = '\n' if new_line else ''
    msg = f"{new_line_str}{timestamp} {indent_str}- {string}"
    Path(os.path.dirname(fpath_log_file)).mkdir(parents=True, exist_ok=True)
    with open(fpath_log_file, 'a+') as f:
        f.write(f"{msg}\n")
    print(msg, end = end)

# set data types for csv inport so that the machine doesn't run out of memory with large files (>0.5M rows)
dtypes = {
    'absolute_path': 'str',
    'relative_path': 'str',
    'data_type': 'str',
    'label': 'str',
    'confidence': 'float64',
    'human_verified': 'bool',
    'bbox_left': 'str',
    'bbox_top': 'str',
    'bbox_right': 'str',
    'bbox_bottom': 'str',
    'file_height': 'str',
    'file_width': 'str',
    'DateTimeOriginal': 'str',
    'DateTime': 'str',
    'DateTimeDigitized': 'str',
    'Latitude': 'str',
    'Longitude': 'str',
    'GPSLink': 'str',
    'Altitude': 'str',
    'Make': 'str',
    'Model': 'str',
    'Flash': 'str',
    'ExifOffset': 'str',
    'ResolutionUnit': 'str',
    'YCbCrPositioning': 'str',
    'XResolution': 'str',
    'YResolution': 'str',
    'ExifVersion': 'str',
    'ComponentsConfiguration': 'str',
    'FlashPixVersion': 'str',
    'ColorSpace': 'str',
    'ExifImageWidth': 'str',
    'ISOSpeedRatings': 'str',
    'ExifImageHeight': 'str',
    'ExposureMode': 'str',
    'WhiteBalance': 'str',
    'SceneCaptureType': 'str',
    'ExposureTime': 'str',
    'Software': 'str',
    'Sharpness': 'str',
    'Saturation': 'str',
    'ReferenceBlackWhite': 'str',
    'n_detections': 'int64',
    'max_confidence': 'float64',
}

# move files into subdirectories
def move_files(file, detection_type, var_file_placement, max_detection_conf, var_sep_conf, dst_root, src_dir, manually_checked):

    # set paths
    new_file = os.path.join(detection_type, file)
    src = os.path.join(src_dir, file)
    dst = os.path.join(dst_root, new_file)
    
    # create subfolder
    Path(os.path.dirname(dst)).mkdir(parents=True, exist_ok=True)
    
    # place image or video in subfolder
    if var_file_placement == 1: # move
        shutil.move(src, dst)
    elif var_file_placement == 2: # copy
        shutil.copy2(src, dst)
        
    # return new relative file path
    return(new_file)

# if gps data can't be retrieved from metadata, read it from image text
def read_gps_text_from_image(image_path):
    log("reading gps text from image", indent = 2)

    image = Image.open(image_path) # TODO: kan dit anders?

    # crop gps text from image dependning on pic size (left, top, right, bottom)
    width, height = image.size
    log(f"input image resolution is {width} * {height}px", indent = 2)
    if width == 2560 and height == 1920:
        log(f"that means that the picture size of camera is set to 'Original'", indent = 2)
        GPS_area = (608, 1840, 1195, 1910)
    elif width == 1920 and height == 1440:
        log(f"that means that the picture size of camera is set to 'Bigger'", indent = 2)
        GPS_area = (454, 1375, 900, 1434)
    else:
        log(f"that means that the picture size of camera is 'small' - the camera is only 2G connected", indent = 2)
        return [2, 2] # TODO: if gps is 2,2 it means that the camera is sending over 2G - make notification
    cropped_image = image.crop(GPS_area)

    # # check if the area is selected properly
    # left = 454
    # right = 900
    # top = 1375
    # bottom = 1434
    # image_to_vis = cv2.imread(fpath_org_img)
    # bb.add(image_to_vis, *[left, top, right, bottom], '', 'red')
    # cv2.imshow('Image', image_to_vis)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()

    # read
    coord_str = pytesseract.image_to_string(cropped_image)

    # convert
    lat, lon = read_gps_from_text(coord_str)

    # return
    return [lat, lon]

def read_gps_from_text(coord_str):

    # convert dms format 
    def dms_to_dd(dir, deg, min, sec):
        if dir == 'W' or dir == 'S':
            dd = -1 * (float(deg) + float(min)/60 + float(sec)/3600)
        else:
            dd = float(deg) + float(min)/60 + float(sec)/3600
        return dd

    # parse
    log(f"read gps text from image '{repr(coord_str)}'", indent = 2)
    
    # convert all separators to whitespace because the parser mixes up ', ’, ", ”, and ° 
    coord_str = re.sub(r'[’”°"*\']', ' ', coord_str).strip() 
    log(f"remove accents and newline from gps text '{coord_str}'", indent = 2)
    
    # it sometimes incorrectly reads 'E' as '£'
    coord_str = re.sub('£', 'E', coord_str) 

    # keep only alphanumeric and whitepace chars to limit noise 
    coord_str = re.sub(r'[^A-Za-z0-9\s]', '', coord_str) 
    log(f"remove non alphanumeric chars from gps text '{coord_str}'", indent = 2)
    
    # separate into useful substrings 
    coord_lst = []
    for part in coord_str.split():
        letters = ''.join(filter(str.isalpha, part))
        if letters:
            coord_lst.append(letters)
        digits = ''.join(filter(str.isdigit, part))
        if digits:
            coord_lst.append(digits)
    log(f"converted gps text to list '{coord_lst}'", indent = 2)
    
    # convert to numeric lat en lon
    if len(coord_lst) == 8:
        direction_lat, degrees_lat, minutes_lat, seconds_lat, direction_lon, degrees_lon, minutes_lon, seconds_lon = coord_lst
        lat = dms_to_dd(direction_lat, degrees_lat, minutes_lat, seconds_lat)
        lon = dms_to_dd(direction_lon, degrees_lon, minutes_lon, seconds_lon)
        log(f"parsed lat {lat} lon {lon}", indent = 2)
    else:
        log(f"could not parse text", indent = 2)
        lat = 0.
        lon = 0.

    # return
    return [lat, lon]

# clean camera trap name
def remove_trailing_zeros(value):
    return re.sub(r'^0+', '', value)

# get seconds elapsed
def calc_sec_elapsed(date_string):
    time_difference = datetime.datetime.now() - datetime.datetime.strptime(date_string, "%Y:%m:%d %H:%M:%S")
    return int(time_difference.total_seconds())

# get date and time separate
def sep_date_time(date_string):
    date_time_object = datetime.datetime.strptime(date_string, "%Y:%m:%d %H:%M:%S")
    return [date_time_object.date(), date_time_object.time()]

# check GPU availability
def fetch_device():
    device = torch.device('cpu')
    if torch.cuda.is_available():
        device = torch.device('cuda')
    try:
        if torch.backends.mps.is_built and torch.backends.mps.is_available():
            device = torch.device('mps')
    except AttributeError:
        pass
    return device

# get exif fields
def fetch_img_exif(full_path):
    with Image.open(full_path) as img:
        log("fetching image exif data", indent = 2)
        dct = {}
        exif_data = img.info.get('exif')
        if exif_data is None:
            return {}
    
    # make sure the fields are properly formatted
    def cast(v):
        if isinstance(v, TiffImagePlugin.IFDRational):
            return float(v)
        elif isinstance(v, tuple):
            return tuple(cast(t) for t in v)
        elif isinstance(v, bytes):
            return v.decode(errors="replace")
        elif isinstance(v, dict):
            for kk, vv in v.items():
                v[kk] = cast(vv)
            return v
        else: return v

    # sort in dictionary
    for k, v in img._getexif().items():
        if k in PIL.ExifTags.TAGS:
            try:
                v = cast(v)
                dct[PIL.ExifTags.TAGS[k]] = v
            except:
                pass
    
    # return
    return dct

# get gps info
def fetch_lat_lon(full_path):   
    try:
        gpsinfo = gpsphoto.getGPSData(full_path)
        log(f"succeeded to fetch gps from metadata lat {gpsinfo['Latitude']} lon {gpsinfo['Longitude']}", indent = 2)
    except:
        log(f"could not fetch gps from metadata, proceeding to read from text", indent = 2)
        lat, lon = read_gps_text_from_image(full_path)
        if lat == 0. and lon == 0.:
            log(f"could not fetch ggpssp from text, proceeding with lat 0.0 lon 0.0", indent = 2)
        else:
            log(f"succeeded to fetch gps from text lat {lat} lon {lon}", indent = 2)
        gpsinfo = {'Latitude': lat,
                    'Longitude': lon}
    return gpsinfo

# funstion to get base64 string from image file
def convert_to_base64(file_fpath):
    with open(file_fpath, 'rb') as f:
        img = Image.open(f)
        img = img.convert("RGB")
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG')
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return image_base64

# decode email header
def decode_subject(header):
    decoded_header = decode_header(header)[0]
    if decoded_header[1] is not None:
        return decoded_header[0].decode(decoded_header[1])
    else:
        return decoded_header[0]

# open email attachment
def fetch_attachment(msg):
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get('Content-Disposition') is None:
            continue
        filename = part.get_filename()
        if bool(filename):
            content_type = part.get_content_type()
            if 'image' in content_type:
                img_data = part.get_payload(decode=True)
                image = Image.open(BytesIO(img_data))
                return image
            elif 'text/plain' in content_type:
                text_data = part.get_payload(decode=True)
                text = text_data.decode()
                return text

# add detection to dict
def add_detection(dict, key, value):
    if key not in dict:
        dict[key] = []
    dict[key].append(value)
    return dict

# initialise the administration csv
def init_admin_csv():
    global admin_csv
    headers = ['img_id', 'full_path_org', 'full_path_vis', 'url_org', 'url_vis', 'filename',
               'project_name', 'camera_id', 'analysed', 'inference_retry_count']
    with open(admin_csv, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

# update information in the admin csv
def update_admin_csv(new_data):
    global admin_csv
    rows = []
    row_exists = False
    
    # read
    with open(admin_csv, 'r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        headers = reader.fieldnames
        
        for row in reader:
            if row['img_id'] == new_data['img_id']:
                row_exists = True
                
                # update
                for key, value in new_data.items():
                    if key in row:
                        row[key] = value
            rows.append(row)
    
    # add
    if not row_exists:
        new_row = {header: '' for header in headers}
        new_row.update(new_data)
        rows.append(new_row)
    
    # write
    with open(admin_csv, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        
    # copy to shared folder
    src = admin_csv
    dst = os.path.join(file_sharing_folder, "admin.csv")
    subprocess.run(['sudo', 'cp', src, dst], check=True)
    log(f"copied admin.csv from '{src}' to '{dst}'.", indent=3)
    

###################################
############ MAIN CODE ############
###################################

# main function to execute the pipeline
script_refresh_idx = 0
def run_script():
    global script_refresh_idx
    try:

        # init 
        log("Starting up XG-WILD")
        log(f"Runnin on {fetch_device()}")

        # read project settings fro xlsx files
        import_project_settings()

        # inital login
        mail_obj = IMAPConnection()
        mail_obj.login()

        # check mail with infinite loop
        while True:
            mail_obj.check_tasks()
            time.sleep(7)
        
    except Exception as e:

        # exit script if exceeding max retries
        if script_refresh_idx >= script_refresh_max:
            print("\n\nEXIT\n\n")
            raise ValueError("Maximum number of retries reached")
            exit(1)

        # log
        log(f"maximum number of in-script retries reached")
        log(f"restarting entire python script attempt {script_refresh_idx} of {script_refresh_max}")

        # log out of IMAP
        try: 
            log(f"logging out of imap")
            mail_obj.logout()
        except:
            log(f"init new imap connection")
            mail_obj = IMAPConnection()
            log(f"logging out of imap")
            mail_obj.logout()

        # error
        log(f"\n\nerror: {e}")
        log(f"traceback: {traceback.print_exc()}\n\n")
        
        # sleep
        sleep_time = script_refresh_start_sec * script_refresh_multiplier ** script_refresh_idx
        log(f"sleep time before initiating script again is {sleep_time} seconds")
        time.sleep(sleep_time)

        # keep track of count and rerun script
        script_refresh_idx += 1
        run_script()

# initially run the script
if __name__ == "__main__":
    
    # init folder and file structure
    if not os.path.isfile(admin_csv):
        init_admin_csv() 
        log(f"initialised admin csv file at '{admin_csv}'")
    if not os.path.exists(fpath_project_specification_dir):
        Path(os.path.dirname(fpath_project_specification_dir)).mkdir(parents=True, exist_ok=True)
        log(f"created project specification folder at '{fpath_project_specification_dir}'")
    if not os.path.exists(fpath_output_dir):
        Path(os.path.dirname(fpath_output_dir)).mkdir(parents=True, exist_ok=True)
        log(f"created output folder at '{fpath_output_dir}'")
    md_dir = os.path.join(curr_dir, "models", "megadetector")
    if not os.path.exists(md_dir):
        Path(md_dir).mkdir(parents=True, exist_ok=True)
        log(f"created megadetector folder at '{md_dir}'")
    
    # run the script
    run_script()



