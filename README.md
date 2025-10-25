# IITU Life
<img src="screenshot.png" style="width: 100%;">

A Weblog for students, teachers, administration of Internation Information Technology University, but not only!

## Main

This is a server for a typical weblog containing, as you might expect, posts, groups, users of different sorts.
Users may join/create groups, where they will leave posts and comments to whatever they like.
Creators of the groups can moderate the content posted on their group and remove posts/comments that violate the rules.
They can also choose moderators from the users subscribed, so they can also help regulate the group.
But there is also global rules, such as the prohibition of NSFW content across all the weblog.
This is done by using the [Deep NN for NSFW Detection](https://github.com/GantMan/nsfw_model).

## Installation

This application was developed and tested on Windows 11 with Python 3.10. It is unknown if the application works with different versions of OS and Python. Additionally, NSFW-detector works with only specific versions of tensorflow and keras. Those provided in requirements.txt seem to work.

Clone the repository from git clone: [https://github.com/lshinigami/Kalymova_Boyarkin](https://github.com/lshinigami/Kalymova_Boyarkin)

Got to the /Kalymova_Boyarkin and install requirements using pip:
```bash
pip install -r requirements.txt
```

## Usage

Before running the application you need to download the NSFW-detector model from this repository:
[https://github.com/GantMan/nsfw_model/releases/tag/1.2.0](https://github.com/GantMan/nsfw_model/releases/tag/1.2.0)

This will download an archive containing `saved_model.h5` which needs to be placed in the /model folder of the application (if it doesn't exist, then create it in the root directory of the application).

Then you can run the server using a simple bash command:
```bash
python main.py
```

Or use the WSGI server of your choice to run it in the production server.

The initial launch will contain no users, groups, posts etc. As the SQLite database is created upon first launch. It can be found in the /database directory.

## Notes

This is a project for the Web Technology discipline at IITU. It was created for educational purposes only by Zhansaya Kalymova and Dmitriy Boyarkin IT2-2312. It should not be considered as a serious application, but rather as a basic web project.