from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128, ObjectId
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.utils import timezone
import re
import logging
import json
import os
import ast
from collections import OrderedDict
from typing import Any
from rest_framework.decorators import api_view, permission_classes,parser_classes
from django.views.decorators.csrf import csrf_exempt

# Auth/permissions
from pyauth.auth import HasRoleAndDataPermission

# Logger setup
logger = logging.getLogger(__name__)