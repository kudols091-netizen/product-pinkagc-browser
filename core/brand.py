"""Nhận diện thương hiệu PinkAgc Browser — một chỗ đổi tên, mọi nơi dùng.

API namespace GIỮ NGUYÊN `/api/v3` (không rebrand) để script automation viết cho GPM
chạy thẳng vào PinkAgc — đó là tính năng tương thích, không phải nhãn.
"""
from __future__ import annotations

APP_NAME = "PinkAgc Browser"
APP_SHORT = "PinkAgc"
VERSION = "0.1.0"                 # bản đóng gói hiện tại (tăng mỗi release)
# JSON công bố bản mới: {"version":"x.y.z","url":"https://.../setup.exe","notes":"..."}; để trống = tắt check-update.
UPDATE_URL = ""
API_NS = "/api/v3"
DEFAULT_PORT = 19996
DEFAULT_DB = "asset/pinkagc.db"
LOGO_FILE = "logo.svg"            # phục vụ từ ui/
