#!/usr/bin/env python2
from setuptools import setup

setup(name='qiniubed',
      version='1.0',
      description='Python Distribution Utilities',
      author='ux_lsl',
      author_email='ux_lsl@163.com',
      packages=['qiniubed'],
      install_requires=[
          'qiniu',
          'pyperclip',
          'click',
          'pyinotify',
          'py-notify'
      ],
      entry_points={
          'console_scripts': [
              'qiniubed = qiniubed.qiniubed:cli'
          ]
      },
  )
