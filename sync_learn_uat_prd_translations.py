#!/usr/bin/env python
import json
import os
import shutil


def get_articles(dir):
    files = {}

    dir = '/home/me/dev/translate-learn/%s' % dir

    for file in os.listdir(dir):
        if file[-5:] == ".json":
            with open(os.path.join(dir, file), "r") as f:
                files[file] = json.load(f)

    return files


def copy_file(uat_folder, uat_file_name, prd_folder, prd_file_name):
    os.makedirs("/home/me/dev/translate-learn/%s" % uat_folder, exist_ok=True)
    os.makedirs("/home/me/dev/translate-learn/%s" % prd_folder, exist_ok=True)

    uat_file = "/home/me/dev/translate-learn/%s/%s" % (uat_folder, uat_file_name)
    prd_file = "/home/me/dev/translate-learn/%s/%s" % (prd_folder, prd_file_name)

    if os.path.exists(prd_file) and not os.path.exists(uat_file):
        print('Copying PRD file %s to UAT file %s' % (prd_file_name, uat_file_name))
        shutil.copyfile(prd_file, uat_file)


uat_articles = get_articles("learn-uat.liferay.com/en/web_content")
prd_articles = get_articles("learn.liferay.com/en/web_content")

uat_files_by_title = {article["title"]: file for file, article in uat_articles.items()}
prd_files_by_title = {article["title"]: file for file, article in prd_articles.items()}

for title, uat_json_file in uat_files_by_title.items():
    if title not in prd_files_by_title:
        print('Unable to find PRD file for %s (%s)' % (uat_json_file, title))
        continue

    uat_file_name = "%s.html" % uat_json_file[:-5]
    prd_file_name = "%s.html" % prd_files_by_title[title][:-5]

    copy_file("learn-uat.liferay.com/ja/web_content", uat_file_name, "learn.liferay.com/ja/web_content", prd_file_name)