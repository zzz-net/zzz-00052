import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calibration_tool import (
    Storage, CalibrationService,
    STATUS_PENDING, STATUS_COMPLETED, STATUS_REVIEWING,
    STATUS_ARCHIVED, User, ROLE_OPERATOR, ROLE_REVIEWER
)


def seed_sample_data(data_dir: str):
    storage = Storage(data_dir)
    service = CalibrationService(storage)

    users = [
        User(username="operator1", role=ROLE_OPERATOR),
        User(username="operator2", role=ROLE_OPERATOR),
        User(username="reviewer1", role=ROLE_REVIEWER),
    ]
    storage.save_users(users)

    if storage.load_instruments():
        print(f"[样例数据] 目录 {data_dir} 已有仪器数据，跳过初始化")
        return

    today = date.today()
    instruments_data = [
        {
            "code": "INS-001",
            "name": "电子天平",
            "model": "FA2004",
            "manufacturer": "上海精科",
            "location": "理化实验室A",
            "cycle_days": 365,
            "last_calibration_date": (today - timedelta(days=370)).isoformat(),
            "owner": "operator1",
            "remark": "万分之一精度"
        },
        {
            "code": "INS-002",
            "name": "数字万用表",
            "model": "Fluke 8846A",
            "manufacturer": "Fluke",
            "location": "电气实验室",
            "cycle_days": 180,
            "last_calibration_date": (today - timedelta(days=200)).isoformat(),
            "owner": "operator2",
            "remark": "6.5位高精度"
        },
        {
            "code": "INS-003",
            "name": "游标卡尺",
            "model": "0-300mm",
            "manufacturer": "哈量",
            "location": "机械车间",
            "cycle_days": 90,
            "last_calibration_date": (today - timedelta(days=80)).isoformat(),
            "owner": "operator1",
            "remark": "精度0.02mm"
        },
        {
            "code": "INS-004",
            "name": "温度计",
            "model": "PT100",
            "manufacturer": "德国JUMO",
            "location": "温控室",
            "cycle_days": 365,
            "last_calibration_date": "",
            "owner": "operator2",
            "remark": "全新设备待校准"
        },
        {
            "code": "INS-005",
            "name": "压力变送器",
            "model": "EJA110A",
            "manufacturer": "横河川仪",
            "location": "生产车间B",
            "cycle_days": 365,
            "last_calibration_date": (today - timedelta(days=30)).isoformat(),
            "owner": "operator1",
            "remark": "近期已校准"
        },
    ]
    for d in instruments_data:
        try:
            service.create_instrument(**d)
        except Exception as e:
            print(f"[样例数据] 跳过仪器 {d['code']}: {e}")

    print(f"[样例数据] 已初始化 {len(instruments_data)} 台仪器和 {len(users)} 个用户")
    print("  用户列表:")
    for u in users:
        print(f"    - {u.username} ({u.role})")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    seed_sample_data(data_dir)
