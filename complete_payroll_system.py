# complete_payroll_system.py - 完整的企業薪資管理系統
from flask import Flask, request, abort, render_template_string, jsonify, session
import sqlite3
import os
from datetime import datetime, timedelta, date
import pytz
import calendar
import json
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import secrets
from functools import wraps

# LINE Bot SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, FollowEvent, TextSendMessage,
    PostbackEvent, PostbackAction, MessageAction, URIAction,
    QuickReply, QuickReplyButton
)

# Flex Message 相關導入
try:
    from linebot.models.flex_message import (
        FlexSendMessage as FlexMessage,
        BubbleContainer, BoxComponent, TextComponent, ButtonComponent,
        CarouselContainer, SeparatorComponent, SpacerComponent
    )
    FLEX_AVAILABLE = True
except ImportError:
    try:
        # 嘗試舊版本導入
        from linebot.models import (
            FlexSendMessage as FlexMessage,
            BubbleContainer, BoxComponent, TextComponent, ButtonComponent,
            CarouselContainer, SeparatorComponent, SpacerComponent
        )
        FLEX_AVAILABLE = True
    except ImportError:
        print("⚠️  Flex Message 不可用，將使用 Quick Reply 按鈕")
        FlexMessage = None
        BubbleContainer = None
        BoxComponent = None
        TextComponent = None
        ButtonComponent = None
        CarouselContainer = None
        SeparatorComponent = None
        SpacerComponent = None
        FLEX_AVAILABLE = False

# Flask 應用初始化
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# LINE Bot 設定
ACCESS_TOKEN = 'MzGhqH9h1ZKP2zwU2+NY+IAqpHxYbCDSAHMKzqcK5bOi5MWWll4/gU7fFy09f7tW5jhq7wmPAE+XzqO1Mqkc7oE/RPI6a0IgYfSFYJAGfB81OU5PjOdYGa4O4dfV34VMsw9NPqK5id7SGqoDXvObcgdB04t89/1O/w1cDnyilFU='
WEBHOOK_SECRET = '389db7eda4b80b0d28086cdc15ae5ec1'

line_bot_api = LineBotApi(ACCESS_TOKEN)
handler = WebhookHandler(WEBHOOK_SECRET)

# 台灣時區設定
TW_TZ = pytz.timezone('Asia/Taipei')

# 按鈕輔助類
class ButtonHelper:
    @staticmethod
    def create_quick_reply_buttons(buttons_data):
        """創建 Quick Reply 按鈕"""
        buttons = []
        for button_data in buttons_data:
            if button_data['type'] == 'message':
                buttons.append(QuickReplyButton(
                    action=MessageAction(
                        label=button_data['label'],
                        text=button_data['text']
                    )
                ))
            elif button_data['type'] == 'postback':
                buttons.append(QuickReplyButton(
                    action=PostbackAction(
                        label=button_data['label'],
                        data=button_data['data'],
                        text=button_data.get('text', button_data['label'])
                    )
                ))
        
        return QuickReply(items=buttons)
    
    @staticmethod
    def create_flex_buttons(buttons_data):
        """創建 Flex Message 按鈕"""
        buttons = []
        for button_data in buttons_data:
            if button_data['type'] == 'message':
                buttons.append(ButtonComponent(
                    action=MessageAction(
                        label=button_data['label'],
                        text=button_data['text']
                    ),
                    style=button_data.get('style', 'primary'),
                    color=button_data.get('color', '#1DB446')
                ))
            elif button_data['type'] == 'postback':
                buttons.append(ButtonComponent(
                    action=PostbackAction(
                        label=button_data['label'],
                        data=button_data['data'],
                        text=button_data.get('text', button_data['label'])
                    ),
                    style=button_data.get('style', 'primary'),
                    color=button_data.get('color', '#1DB446')
                ))
        
        return buttons

# 資料庫管理類
class DatabaseManager:
    def __init__(self, db_path='payroll_system.db'):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """取得資料庫連接"""
        return sqlite3.connect(self.db_path)
    
    def init_database(self):
        """初始化完整資料庫結構"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. 角色表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_name TEXT UNIQUE NOT NULL,
                    role_description TEXT,
                    permissions TEXT,  -- JSON格式存儲權限
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 2. 部門表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS departments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dept_name TEXT UNIQUE NOT NULL,
                    dept_code TEXT UNIQUE,
                    manager_id TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 3. 用戶表（擴展版）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE NOT NULL,
                    employee_id TEXT UNIQUE,
                    name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    department_id INTEGER,
                    position TEXT,
                    hire_date DATE,
                    status TEXT DEFAULT 'active',
                    line_profile_picture TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (department_id) REFERENCES departments (id)
                )
            ''')
            
            # 4. 用戶角色關聯表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    assigned_by TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (role_id) REFERENCES roles (id),
                    UNIQUE(user_id, role_id)
                )
            ''')
            
            # 5. 考勤記錄表（擴展版）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    record_date DATE NOT NULL,
                    action_type TEXT NOT NULL,  -- clock_in, clock_out, break_start, break_end
                    record_time TIMESTAMP NOT NULL,
                    taiwan_time TEXT NOT NULL,
                    location TEXT,
                    device_info TEXT,
                    ip_address TEXT,
                    notes TEXT,
                    status TEXT DEFAULT 'normal',  -- normal, late, early, overtime
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # 6. 薪資結構表（擴展版）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS salary_structures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    base_salary REAL DEFAULT 0,
                    hourly_rate REAL DEFAULT 0,
                    overtime_rate REAL DEFAULT 1.33,
                    holiday_rate REAL DEFAULT 2.0,
                    night_shift_rate REAL DEFAULT 1.33,
                    position_allowance REAL DEFAULT 0,
                    transport_allowance REAL DEFAULT 0,
                    meal_allowance REAL DEFAULT 0,
                    housing_allowance REAL DEFAULT 0,
                    skill_allowance REAL DEFAULT 0,
                    other_allowances REAL DEFAULT 0,
                    effective_date DATE NOT NULL,
                    end_date DATE,
                    status TEXT DEFAULT 'active',
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # 7. 扣款設定表（擴展版）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS salary_deductions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    labor_insurance REAL DEFAULT 0,
                    health_insurance REAL DEFAULT 0,
                    unemployment_insurance REAL DEFAULT 0,
                    income_tax REAL DEFAULT 0,
                    pension REAL DEFAULT 0,
                    union_fee REAL DEFAULT 0,
                    loan_deduction REAL DEFAULT 0,
                    other_deductions REAL DEFAULT 0,
                    effective_date DATE NOT NULL,
                    end_date DATE,
                    status TEXT DEFAULT 'active',
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # 8. 請假類型表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leave_types (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type_name TEXT UNIQUE NOT NULL,
                    type_code TEXT UNIQUE NOT NULL,
                    is_paid BOOLEAN DEFAULT 0,
                    max_days_per_year REAL DEFAULT 0,
                    description TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 9. 請假申請表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leave_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    leave_type_id INTEGER NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    start_time TIME,
                    end_time TIME,
                    total_hours REAL NOT NULL,
                    reason TEXT,
                    application_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',  -- pending, approved, rejected, cancelled
                    approved_by TEXT,
                    approved_at TIMESTAMP,
                    reject_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (leave_type_id) REFERENCES leave_types (id)
                )
            ''')
            
            # 10. 加班申請表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS overtime_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    overtime_date DATE NOT NULL,
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    total_hours REAL NOT NULL,
                    overtime_type TEXT NOT NULL,  -- weekday, weekend, holiday
                    reason TEXT,
                    application_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',  -- pending, approved, rejected, cancelled
                    approved_by TEXT,
                    approved_at TIMESTAMP,
                    reject_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # 11. 薪資記錄表（擴展版）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payroll_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    period_year INTEGER NOT NULL,
                    period_month INTEGER NOT NULL,
                    work_days INTEGER DEFAULT 0,
                    total_work_hours REAL DEFAULT 0,
                    regular_hours REAL DEFAULT 0,
                    overtime_hours REAL DEFAULT 0,
                    holiday_hours REAL DEFAULT 0,
                    night_shift_hours REAL DEFAULT 0,
                    leave_hours REAL DEFAULT 0,
                    base_salary REAL DEFAULT 0,
                    overtime_pay REAL DEFAULT 0,
                    holiday_pay REAL DEFAULT 0,
                    night_shift_pay REAL DEFAULT 0,
                    total_allowances REAL DEFAULT 0,
                    gross_salary REAL DEFAULT 0,
                    total_deductions REAL DEFAULT 0,
                    net_salary REAL DEFAULT 0,
                    bonus REAL DEFAULT 0,
                    commission REAL DEFAULT 0,
                    status TEXT DEFAULT 'draft',  -- draft, confirmed, paid
                    calculated_by TEXT,
                    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confirmed_by TEXT,
                    confirmed_at TIMESTAMP,
                    paid_by TEXT,
                    paid_at TIMESTAMP,
                    payment_method TEXT,
                    notes TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    UNIQUE(user_id, period_year, period_month)
                )
            ''')
            
            # 12. 薪資明細表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payroll_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payroll_record_id INTEGER NOT NULL,
                    item_category TEXT NOT NULL,  -- salary, allowance, deduction, bonus
                    item_name TEXT NOT NULL,
                    item_code TEXT,
                    amount REAL NOT NULL,
                    calculation_base TEXT,
                    calculation_rate REAL,
                    notes TEXT,
                    FOREIGN KEY (payroll_record_id) REFERENCES payroll_records (id)
                )
            ''')
            
            # 13. 系統設定表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    setting_category TEXT NOT NULL,
                    setting_key TEXT NOT NULL,
                    setting_value TEXT NOT NULL,
                    setting_type TEXT DEFAULT 'string',  -- string, number, boolean, json
                    description TEXT,
                    is_public BOOLEAN DEFAULT 0,
                    updated_by TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(setting_category, setting_key)
                )
            ''')
            
            # 14. 操作日誌表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS operation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    operation_object TEXT,
                    operation_details TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    result TEXT DEFAULT 'success',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # 15. 通知表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    notification_type TEXT NOT NULL,  -- info, warning, error, success
                    is_read BOOLEAN DEFAULT 0,
                    priority INTEGER DEFAULT 1,  -- 1=low, 2=medium, 3=high
                    related_object_type TEXT,
                    related_object_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # 插入預設數據
            self._insert_default_data(cursor)
            
            conn.commit()
            print("✅ 資料庫初始化完成")
            
        except Exception as e:
            print(f"❌ 資料庫初始化失敗: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def _insert_default_data(self, cursor):
        """插入預設數據"""
        
        # 預設角色
        default_roles = [
            ('admin', '系統管理員', '{"all": true}'),
            ('hr', '人事管理員', '{"payroll": true, "attendance": true, "reports": true}'),
            ('manager', '部門主管', '{"team_payroll": true, "team_attendance": true, "approve": true}'),
            ('employee', '一般員工', '{"self_payroll": true, "self_attendance": true, "apply": true}')
        ]
        
        for role_name, description, permissions in default_roles:
            cursor.execute('''
                INSERT OR IGNORE INTO roles (role_name, role_description, permissions)
                VALUES (?, ?, ?)
            ''', (role_name, description, permissions))
        
        # 預設部門
        default_departments = [
            ('總經理室', 'CEO', '公司最高決策單位'),
            ('人事部', 'HR', '人力資源管理'),
            ('財務部', 'FIN', '財務會計管理'),
            ('業務部', 'SALES', '業務銷售'),
            ('技術部', 'TECH', '技術開發'),
            ('行政部', 'ADMIN', '行政庶務')
        ]
        
        for dept_name, dept_code, description in default_departments:
            cursor.execute('''
                INSERT OR IGNORE INTO departments (dept_name, dept_code, description)
                VALUES (?, ?, ?)
            ''', (dept_name, dept_code, description))
        
        # 預設請假類型
        default_leave_types = [
            ('特休假', 'ANNUAL', 1, 14, '年度特休假'),
            ('病假', 'SICK', 1, 30, '因病請假'),
            ('事假', 'PERSONAL', 0, 14, '個人事務請假'),
            ('婚假', 'WEDDING', 1, 8, '結婚假'),
            ('喪假', 'FUNERAL', 1, 8, '喪葬假'),
            ('產假', 'MATERNITY', 1, 56, '產假'),
            ('陪產假', 'PATERNITY', 1, 5, '陪產假')
        ]
        
        for type_name, type_code, is_paid, max_days, description in default_leave_types:
            cursor.execute('''
                INSERT OR IGNORE INTO leave_types 
                (type_name, type_code, is_paid, max_days_per_year, description)
                VALUES (?, ?, ?, ?, ?)
            ''', (type_name, type_code, is_paid, max_days, description))
        
        # 預設系統設定
        default_settings = [
            # 考勤設定
            ('attendance', 'standard_work_hours', '8', 'number', '標準工作時數/天'),
            ('attendance', 'work_days_per_month', '22', 'number', '每月標準工作天數'),
            ('attendance', 'late_threshold_minutes', '15', 'number', '遲到門檻(分鐘)'),
            ('attendance', 'overtime_threshold_hours', '8', 'number', '加班門檻時數'),
            
            # 薪資設定
            ('payroll', 'minimum_wage_hourly', '183', 'number', '基本工資(時薪)'),
            ('payroll', 'minimum_wage_monthly', '27470', 'number', '基本工資(月薪)'),
            ('payroll', 'overtime_rate_weekday', '1.33', 'number', '平日加班費率'),
            ('payroll', 'overtime_rate_weekend', '1.67', 'number', '假日加班費率'),
            ('payroll', 'overtime_rate_holiday', '2.0', 'number', '國定假日加班費率'),
            
            # 保險費率
            ('insurance', 'labor_insurance_rate', '0.105', 'number', '勞保費率'),
            ('insurance', 'health_insurance_rate', '0.0517', 'number', '健保費率'),
            ('insurance', 'unemployment_insurance_rate', '0.01', 'number', '就業保險費率'),
            ('insurance', 'pension_rate', '0.06', 'number', '勞退提撥率'),
            
            # 稅務設定
            ('tax', 'income_tax_threshold', '40000', 'number', '所得稅起徵點'),
            ('tax', 'income_tax_rate', '0.05', 'number', '所得稅率'),
            
            # 系統設定
            ('system', 'company_name', '範例公司股份有限公司', 'string', '公司名稱'),
            ('system', 'company_address', '台北市信義區', 'string', '公司地址'),
            ('system', 'payroll_cutoff_day', '25', 'number', '薪資計算截止日'),
            ('system', 'payday', '5', 'number', '發薪日')
        ]
        
        for category, key, value, type_, description in default_settings:
            cursor.execute('''
                INSERT OR IGNORE INTO system_settings 
                (setting_category, setting_key, setting_value, setting_type, description)
                VALUES (?, ?, ?, ?, ?)
            ''', (category, key, value, type_, description))

# 權限管理類
class PermissionManager:
    def __init__(self, db_manager):
        self.db = db_manager
    
    def get_user_permissions(self, user_id):
        """取得用戶權限"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT r.permissions 
            FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.id
            WHERE u.user_id = ? AND u.status = 'active'
        ''', (user_id,))
        
        permissions = []
        for row in cursor.fetchall():
            try:
                perm = json.loads(row[0])
                permissions.append(perm)
            except:
                continue
        
        conn.close()
        
        # 合併權限
        merged_permissions = {}
        for perm in permissions:
            merged_permissions.update(perm)
        
        return merged_permissions
    
    def has_permission(self, user_id, permission):
        """檢查用戶是否有特定權限"""
        permissions = self.get_user_permissions(user_id)
        
        # 管理員有所有權限
        if permissions.get('all', False):
            return True
        
        return permissions.get(permission, False)
    
    def assign_role(self, user_id, role_name, assigned_by):
        """指派角色給用戶"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # 取得角色ID
        cursor.execute('SELECT id FROM roles WHERE role_name = ?', (role_name,))
        role = cursor.fetchone()
        
        if not role:
            conn.close()
            return False
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO user_roles (user_id, role_id, assigned_by)
                VALUES (?, ?, ?)
            ''', (user_id, role[0], assigned_by))
            
            conn.commit()
            conn.close()
            return True
        except:
            conn.close()
            return False
    
    def get_user_roles(self, user_id):
        """取得用戶角色列表"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT r.role_name, r.role_description
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = ?
        ''', (user_id,))
        
        roles = cursor.fetchall()
        conn.close()
        
        return [{'name': role[0], 'description': role[1]} for role in roles]

# 用戶管理類
class UserManager:
    def __init__(self, db_manager, permission_manager):
        self.db = db_manager
        self.perm = permission_manager
    
    def create_or_get_user(self, user_id, name=None):
        """創建或取得用戶"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 檢查用戶是否存在
            cursor.execute('SELECT id, name FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
            
            if not user:
                # 創建新用戶
                if not name:
                    try:
                        profile = line_bot_api.get_profile(user_id)
                        name = profile.display_name
                    except:
                        name = f"用戶{user_id[-4:]}"
                
                # 生成員工編號
                employee_id = self._generate_employee_id(cursor)
                
                cursor.execute('''
                    INSERT INTO users (user_id, employee_id, name, hire_date)
                    VALUES (?, ?, ?, DATE('now'))
                ''', (user_id, employee_id, name))
                
                # 預設指派員工角色
                cursor.execute('SELECT id FROM roles WHERE role_name = "employee"')
                role = cursor.fetchone()
                if role:
                    cursor.execute('''
                        INSERT INTO user_roles (user_id, role_id)
                        VALUES (?, ?)
                    ''', (user_id, role[0]))
                
                conn.commit()
                print(f"✅ 新用戶已創建: {name} ({employee_id})")
            
            conn.close()
            return True
            
        except Exception as e:
            print(f"❌ 用戶管理錯誤: {e}")
            conn.close()
            return False
    
    def _generate_employee_id(self, cursor):
        """生成員工編號"""
        cursor.execute('SELECT COUNT(*) FROM users')
        count = cursor.fetchone()[0]
        return f"EMP{count + 1:05d}"
    
    def get_user_info(self, user_id):
        """取得用戶詳細資訊"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT u.*, d.dept_name
            FROM users u
            LEFT JOIN departments d ON u.department_id = d.id
            WHERE u.user_id = ?
        ''', (user_id,))
        
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[1],
                'employee_id': user[2],
                'name': user[3],
                'email': user[4],
                'phone': user[5],
                'department': user[12] if user[12] else '未分配',
                'position': user[7],
                'hire_date': user[8],
                'status': user[9]
            }
        return None
    
    def update_user_info(self, user_id, update_data, updated_by):
        """更新用戶資訊"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # 構建更新語句
        fields = []
        values = []
        
        for field, value in update_data.items():
            if field in ['name', 'email', 'phone', 'department_id', 'position']:
                fields.append(f"{field} = ?")
                values.append(value)
        
        if not fields:
            conn.close()
            return False
        
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(user_id)
        
        try:
            cursor.execute(f'''
                UPDATE users SET {', '.join(fields)}
                WHERE user_id = ?
            ''', values)
            
            conn.commit()
            conn.close()
            return True
        except:
            conn.close()
            return False

# 考勤管理類
class AttendanceManager:
    def __init__(self, db_manager, permission_manager):
        self.db = db_manager
        self.perm = permission_manager
    
    def clock_in_out(self, user_id, action_type, location=None):
        """上下班打卡"""
        taiwan_time = datetime.now(TW_TZ)
        record_date = taiwan_time.date()
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 檢查當日是否已有相同動作
            cursor.execute('''
                SELECT id FROM attendance_records 
                WHERE user_id = ? AND record_date = ? AND action_type = ?
                ORDER BY record_time DESC LIMIT 1
            ''', (user_id, record_date, action_type))
            
            existing = cursor.fetchone()
            
            # 判斷狀態
            status = self._determine_status(action_type, taiwan_time)
            
            cursor.execute('''
                INSERT INTO attendance_records 
                (user_id, record_date, action_type, record_time, taiwan_time, location, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, record_date, action_type, 
                taiwan_time.isoformat(), taiwan_time.strftime('%Y-%m-%d %H:%M:%S'),
                location, status
            ))
            
            conn.commit()
            record_id = cursor.lastrowid
            conn.close()
            
            return {
                'success': True,
                'record_id': record_id,
                'time': taiwan_time.strftime('%H:%M'),
                'status': status,
                'message': self._get_status_message(action_type, status)
            }
            
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    def _determine_status(self, action_type, time_obj):
        """判斷考勤狀態"""
        hour = time_obj.hour
        minute = time_obj.minute
        
        if action_type == 'clock_in':
            # 上班時間判斷 (假設9:00正常上班)
            if hour < 9 or (hour == 9 and minute <= 15):
                return 'normal'
            else:
                return 'late'
        elif action_type == 'clock_out':
            # 下班時間判斷 (假設18:00正常下班)
            if hour >= 18:
                return 'normal'
            else:
                return 'early'
        
        return 'normal'
    
    def _get_status_message(self, action_type, status):
        """取得狀態訊息"""
        messages = {
            ('clock_in', 'normal'): '正常上班',
            ('clock_in', 'late'): '遲到',
            ('clock_out', 'normal'): '正常下班',
            ('clock_out', 'early'): '早退',
            ('clock_out', 'overtime'): '加班'
        }
        return messages.get((action_type, status), '已記錄')
    
    def get_attendance_summary(self, user_id, year, month):
        """取得考勤統計"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                action_type, status, COUNT(*) as count,
                MIN(taiwan_time) as first_time,
                MAX(taiwan_time) as last_time
            FROM attendance_records 
            WHERE user_id = ? AND strftime('%Y', record_date) = ? 
            AND strftime('%m', record_date) = ?
            GROUP BY action_type, status
        ''', (user_id, str(year), f"{month:02d}"))
        
        results = cursor.fetchall()
        conn.close()
        
        summary = {
            'total_days': 0,
            'normal_days': 0,
            'late_count': 0,
            'early_count': 0,
            'overtime_count': 0,
            'first_checkin': None,
            'last_checkout': None
        }
        
        for action_type, status, count, first_time, last_time in results:
            if action_type == 'clock_in':
                summary['total_days'] += count
                if status == 'normal':
                    summary['normal_days'] += count
                elif status == 'late':
                    summary['late_count'] += count
                    
                if not summary['first_checkin'] or first_time < summary['first_checkin']:
                    summary['first_checkin'] = first_time
                    
            elif action_type == 'clock_out':
                if status == 'early':
                    summary['early_count'] += count
                elif status == 'overtime':
                    summary['overtime_count'] += count
                    
                if not summary['last_checkout'] or last_time > summary['last_checkout']:
                    summary['last_checkout'] = last_time
        
        return summary
    
    def calculate_work_hours(self, user_id, year, month):
        """計算工作時數"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT record_date, action_type, record_time
            FROM attendance_records 
            WHERE user_id = ? AND strftime('%Y', record_date) = ? 
            AND strftime('%m', record_date) = ?
            ORDER BY record_date, record_time
        ''', (user_id, str(year), f"{month:02d}"))
        
        records = cursor.fetchall()
        conn.close()
        
        daily_hours = {}
        current_date = None
        clock_in_time = None
        
        for record_date, action_type, record_time in records:
            if record_date != current_date:
                current_date = record_date
                clock_in_time = None
            
            time_obj = datetime.fromisoformat(record_time)
            
            if action_type == 'clock_in':
                clock_in_time = time_obj
            elif action_type == 'clock_out' and clock_in_time:
                work_hours = (time_obj - clock_in_time).total_seconds() / 3600
                daily_hours[record_date] = daily_hours.get(record_date, 0) + work_hours
                clock_in_time = None
        
        total_hours = sum(daily_hours.values())
        work_days = len(daily_hours)
        
        # 區分正常工時和加班工時
        standard_hours_per_day = 8
        regular_hours = 0
        overtime_hours = 0
        
        for date, hours in daily_hours.items():
            if hours <= standard_hours_per_day:
                regular_hours += hours
            else:
                regular_hours += standard_hours_per_day
                overtime_hours += (hours - standard_hours_per_day)
        
        return {
            'total_hours': round(total_hours, 2),
            'regular_hours': round(regular_hours, 2),
            'overtime_hours': round(overtime_hours, 2),
            'work_days': work_days,
            'daily_hours': daily_hours
        }

# 請假管理類
class LeaveManager:
    def __init__(self, db_manager, permission_manager):
        self.db = db_manager
        self.perm = permission_manager
    
    def apply_leave(self, user_id, leave_type_id, start_date, end_date, reason, start_time=None, end_time=None):
        """申請請假"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 計算請假時數
            total_hours = self._calculate_leave_hours(start_date, end_date, start_time, end_time)
            
            cursor.execute('''
                INSERT INTO leave_applications 
                (user_id, leave_type_id, start_date, end_date, start_time, end_time, total_hours, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, leave_type_id, start_date, end_date, start_time, end_time, total_hours, reason))
            
            application_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            return {'success': True, 'application_id': application_id}
            
        except Exception as e:
            conn.close()
            return {'success': False, 'error': str(e)}
    
    def _calculate_leave_hours(self, start_date, end_date, start_time, end_time):
        """計算請假時數"""
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        days = (end_date - start_date).days + 1
        
        if start_time and end_time:
            # 時假計算
            if isinstance(start_time, str):
                start_time = datetime.strptime(start_time, '%H:%M').time()
            if isinstance(end_time, str):
                end_time = datetime.strptime(end_time, '%H:%M').time()
            
            start_datetime = datetime.combine(start_date, start_time)
            end_datetime = datetime.combine(end_date, end_time)
            
            return (end_datetime - start_datetime).total_seconds() / 3600
        else:
            # 日假計算 (一天8小時)
            return days * 8
    
    def approve_leave(self, application_id, approved_by, approved=True, reject_reason=None):
        """核准/駁回請假"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            status = 'approved' if approved else 'rejected'
            
            cursor.execute('''
                UPDATE leave_applications 
                SET status = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP, reject_reason = ?
                WHERE id = ?
            ''', (status, approved_by, reject_reason, application_id))
            
            conn.commit()
            conn.close()
            return True
            
        except:
            conn.close()
            return False
    
    def get_leave_applications(self, user_id=None, status=None, limit=10):
        """取得請假申請列表"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        where_conditions = []
        params = []
        
        if user_id:
            where_conditions.append("la.user_id = ?")
            params.append(user_id)
        
        if status:
            where_conditions.append("la.status = ?")
            params.append(status)
        
        where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        params.append(limit)
        
        cursor.execute(f'''
            SELECT la.*, u.name, lt.type_name
            FROM leave_applications la
            JOIN users u ON la.user_id = u.user_id
            JOIN leave_types lt ON la.leave_type_id = lt.id
            {where_clause}
            ORDER BY la.application_date DESC
            LIMIT ?
        ''', params)
        
        applications = cursor.fetchall()
        conn.close()
        
        return [self._format_leave_application(app) for app in applications]
    
    def _format_leave_application(self, app_data):
        """格式化請假申請資料"""
        return {
            'id': app_data[0],
            'user_id': app_data[1],
            'user_name': app_data[13],
            'leave_type': app_data[14],
            'start_date': app_data[3],
            'end_date': app_data[4],
            'total_hours': app_data[7],
            'reason': app_data[8],
            'status': app_data[10],
            'application_date': app_data[9]
        }

# 薪資計算引擎
class PayrollCalculator:
    def __init__(self, db_manager, permission_manager):
        self.db = db_manager
        self.perm = permission_manager
    
    def calculate_monthly_payroll(self, user_id, year, month):
        """計算月薪資"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 取得用戶薪資結構
            salary_structure = self._get_salary_structure(user_id, cursor)
            
            # 取得扣款設定
            deductions = self._get_deduction_settings(user_id, cursor)
            
            # 計算工時
            attendance_mgr = AttendanceManager(self.db, self.perm)
            work_data = attendance_mgr.calculate_work_hours(user_id, year, month)
            
            # 計算各項薪資
            calculations = self._calculate_salary_components(salary_structure, work_data)
            
            # 計算扣款
            deduction_details = self._calculate_deductions(calculations['gross_salary'], deductions)
            
            # 計算實領薪資
            net_salary = calculations['gross_salary'] - deduction_details['total_deductions']
            
            # 儲存薪資記錄
            payroll_id = self._save_payroll_record(user_id, year, month, work_data, calculations, deduction_details, net_salary, cursor)
            
            conn.commit()
            conn.close()
            
            return {
                'payroll_id': payroll_id,
                'work_data': work_data,
                'calculations': calculations,
                'deduction_details': deduction_details,
                'net_salary': net_salary
            }
            
        except Exception as e:
            conn.close()
            raise e
    
    def _get_salary_structure(self, user_id, cursor):
        """取得薪資結構"""
        cursor.execute('''
            SELECT * FROM salary_structures 
            WHERE user_id = ? AND status = 'active'
            ORDER BY effective_date DESC LIMIT 1
        ''', (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            return {
                'base_salary': result[2] or 0,
                'hourly_rate': result[3] or 183,
                'overtime_rate': result[4] or 1.33,
                'holiday_rate': result[5] or 2.0,
                'night_shift_rate': result[6] or 1.33,
                'position_allowance': result[7] or 0,
                'transport_allowance': result[8] or 0,
                'meal_allowance': result[9] or 0,
                'housing_allowance': result[10] or 0,
                'skill_allowance': result[11] or 0,
                'other_allowances': result[12] or 0
            }
        
        # 預設值
        return {
            'base_salary': 0,
            'hourly_rate': 183,
            'overtime_rate': 1.33,
            'holiday_rate': 2.0,
            'night_shift_rate': 1.33,
            'position_allowance': 0,
            'transport_allowance': 0,
            'meal_allowance': 0,
            'housing_allowance': 0,
            'skill_allowance': 0,
            'other_allowances': 0
        }
    
    def _get_deduction_settings(self, user_id, cursor):
        """取得扣款設定"""
        cursor.execute('''
            SELECT * FROM salary_deductions 
            WHERE user_id = ? AND status = 'active'
            ORDER BY effective_date DESC LIMIT 1
        ''', (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            return {
                'labor_insurance': result[2] or 0,
                'health_insurance': result[3] or 0,
                'unemployment_insurance': result[4] or 0,
                'income_tax': result[5] or 0,
                'pension': result[6] or 0,
                'union_fee': result[7] or 0,
                'loan_deduction': result[8] or 0,
                'other_deductions': result[9] or 0
            }
        
        return {
            'labor_insurance': 0,
            'health_insurance': 0,
            'unemployment_insurance': 0,
            'income_tax': 0,
            'pension': 0,
            'union_fee': 0,
            'loan_deduction': 0,
            'other_deductions': 0
        }
    
    def _calculate_salary_components(self, salary_structure, work_data):
        """計算薪資組成"""
        calculations = {}
        
        # 基本薪資
        if salary_structure['base_salary'] > 0:
            # 月薪制
            base_salary = salary_structure['base_salary']
        else:
            # 時薪制
            base_salary = work_data['regular_hours'] * salary_structure['hourly_rate']
        
        calculations['base_salary'] = round(base_salary, 0)
        
        # 加班費
        overtime_pay = work_data['overtime_hours'] * salary_structure['hourly_rate'] * salary_structure['overtime_rate']
        calculations['overtime_pay'] = round(overtime_pay, 0)
        
        # 假日加班費 (暫時為0，可後續擴充)
        calculations['holiday_pay'] = 0
        
        # 夜班津貼 (暫時為0，可後續擴充)
        calculations['night_shift_pay'] = 0
        
        # 各項津貼
        total_allowances = (
            salary_structure['position_allowance'] +
            salary_structure['transport_allowance'] +
            salary_structure['meal_allowance'] +
            salary_structure['housing_allowance'] +
            salary_structure['skill_allowance'] +
            salary_structure['other_allowances']
        )
        calculations['total_allowances'] = round(total_allowances, 0)
        
        # 薪資總額
        gross_salary = (
            calculations['base_salary'] +
            calculations['overtime_pay'] +
            calculations['holiday_pay'] +
            calculations['night_shift_pay'] +
            calculations['total_allowances']
        )
        calculations['gross_salary'] = round(gross_salary, 0)
        
        return calculations
    
    def _calculate_deductions(self, gross_salary, deductions):
        """計算扣款項目"""
        details = {}
        
        # 如果沒有設定具體扣款，則自動計算
        if deductions['labor_insurance'] == 0:
            details['labor_insurance'] = round(gross_salary * 0.105 * 0.2, 0)  # 員工負擔20%
        else:
            details['labor_insurance'] = deductions['labor_insurance']
        
        if deductions['health_insurance'] == 0:
            details['health_insurance'] = round(gross_salary * 0.0517 * 0.3, 0)  # 員工負擔30%
        else:
            details['health_insurance'] = deductions['health_insurance']
        
        if deductions['unemployment_insurance'] == 0:
            details['unemployment_insurance'] = round(gross_salary * 0.01 * 0.2, 0)  # 員工負擔20%
        else:
            details['unemployment_insurance'] = deductions['unemployment_insurance']
        
        if deductions['pension'] == 0:
            details['pension'] = round(gross_salary * 0.06, 0)  # 6%提撥
        else:
            details['pension'] = deductions['pension']
        
        # 所得稅簡化計算
        if deductions['income_tax'] == 0 and gross_salary > 40000:
            details['income_tax'] = round((gross_salary - 40000) * 0.05, 0)
        else:
            details['income_tax'] = deductions['income_tax']
        
        details['union_fee'] = deductions['union_fee']
        details['loan_deduction'] = deductions['loan_deduction']
        details['other_deductions'] = deductions['other_deductions']
        
        details['total_deductions'] = sum(details.values())
        
        return details
    
    def _save_payroll_record(self, user_id, year, month, work_data, calculations, deduction_details, net_salary, cursor):
        """儲存薪資記錄"""
        cursor.execute('''
            INSERT OR REPLACE INTO payroll_records (
                user_id, period_year, period_month, work_days, total_work_hours,
                regular_hours, overtime_hours, base_salary, overtime_pay,
                total_allowances, gross_salary, total_deductions, net_salary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, year, month, work_data['work_days'], work_data['total_hours'],
            work_data['regular_hours'], work_data['overtime_hours'],
            calculations['base_salary'], calculations['overtime_pay'],
            calculations['total_allowances'], calculations['gross_salary'],
            deduction_details['total_deductions'], net_salary
        ))
        
        payroll_id = cursor.lastrowid
        
        # 清除舊的薪資明細
        cursor.execute('DELETE FROM payroll_details WHERE payroll_record_id = ?', (payroll_id,))
        
        # 新增薪資明細
        details = [
            ('salary', '基本薪資', calculations['base_salary']),
            ('salary', '加班費', calculations['overtime_pay']),
            ('allowance', '各項津貼', calculations['total_allowances']),
            ('deduction', '勞保費', deduction_details['labor_insurance']),
            ('deduction', '健保費', deduction_details['health_insurance']),
            ('deduction', '就業保險', deduction_details['unemployment_insurance']),
            ('deduction', '退休金', deduction_details['pension']),
            ('deduction', '所得稅', deduction_details['income_tax'])
        ]
        
        for category, name, amount in details:
            if amount > 0:
                cursor.execute('''
                    INSERT INTO payroll_details (payroll_record_id, item_category, item_name, amount)
                    VALUES (?, ?, ?, ?)
                ''', (payroll_id, category, name, amount))
        
        return payroll_id

# 用戶狀態管理類
class UserStateManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.user_states = {}  # 記憶體中的狀態管理
    
    def set_user_state(self, user_id, state, data=None):
        """設定用戶狀態"""
        self.user_states[user_id] = {
            'state': state,
            'data': data or {},
            'timestamp': datetime.now()
        }
    
    def get_user_state(self, user_id):
        """取得用戶狀態"""
        return self.user_states.get(user_id, {'state': 'normal', 'data': {}})
    
    def clear_user_state(self, user_id):
        """清除用戶狀態"""
        if user_id in self.user_states:
            del self.user_states[user_id]
    
    def cleanup_expired_states(self):
        """清理過期狀態（超過30分鐘）"""
        now = datetime.now()
        expired_users = []
        
        for user_id, state_info in self.user_states.items():
            if (now - state_info['timestamp']).total_seconds() > 1800:  # 30分鐘
                expired_users.append(user_id)
        
        for user_id in expired_users:
            del self.user_states[user_id]

# LINE Bot 訊息處理器
class LineMessageHandler:
    def __init__(self, db_manager, permission_manager):
        self.db = db_manager
        self.perm = permission_manager
        self.user_mgr = UserManager(db_manager, permission_manager)
        self.attendance_mgr = AttendanceManager(db_manager, permission_manager)
        self.leave_mgr = LeaveManager(db_manager, permission_manager)
        self.payroll_calc = PayrollCalculator(db_manager, permission_manager)
        self.state_mgr = UserStateManager(db_manager)
        self.button_helper = ButtonHelper()
    
    def handle_text_message(self, user_id, text):
        """處理文字訊息"""
        text = text.strip()
        
        # 確保用戶存在
        self.user_mgr.create_or_get_user(user_id)
        
        # 清理過期狀態
        self.state_mgr.cleanup_expired_states()
        
        # 取得用戶當前狀態
        user_state = self.state_mgr.get_user_state(user_id)
        current_state = user_state['state']
        
        # 檢查是否有取消指令
        if text in ['取消', '結束', '退出']:
            self.state_mgr.clear_user_state(user_id)
            return TextSendMessage(text="✅ 已取消當前操作\n\n輸入「你好」查看主選單")
        
        # 根據當前狀態處理訊息
        if current_state == 'leave_type_selection':
            return self._handle_leave_type_selection(user_id, text)
        elif current_state == 'leave_date_input':
            return self._handle_leave_date_input(user_id, text)
        elif current_state == 'leave_reason_input':
            return self._handle_leave_reason_input(user_id, text)
        elif current_state == 'admin_employee_selection':
            return self._handle_admin_employee_selection(user_id, text)
        elif current_state == 'salary_setting':
            return self._handle_salary_setting(user_id, text)
        elif current_state == 'leave_approval_selection':
            return self._handle_leave_approval_selection(user_id, text)
        elif current_state == 'leave_approval_decision':
            return self._handle_leave_approval_decision(user_id, text)
        elif current_state == 'leave_approval_reject_reason':
            return self._handle_leave_approval_reject_reason(user_id, text)
        
        # 正常狀態下的指令處理
        # 取得用戶權限
        permissions = self.perm.get_user_permissions(user_id)
        
        # 考勤功能
        if text == '上班' or text == '打卡':
            return self._handle_clock_in(user_id)
        elif text == '下班':
            return self._handle_clock_out(user_id)
        elif text == '考勤查詢' or text == '考勤':
            return self._handle_attendance_query(user_id)
        
        # 薪資功能
        elif text == '薪資單' or text == '薪水單':
            return self._handle_payslip_request(user_id)
        elif text == '薪資歷史':
            return self._handle_payroll_history(user_id)
        
        # 請假功能
        elif text == '請假申請' or text == '請假':
            return self._handle_leave_application_start(user_id)
        elif text == '請假查詢':
            return self._handle_leave_query(user_id)
        
        # 管理員功能
        elif self.perm.has_permission(user_id, 'all') or self.perm.has_permission(user_id, 'payroll'):
            if text == '管理員功能':
                return self._handle_admin_menu(user_id)
            elif text == '薪資統計':
                return self._handle_payroll_statistics(user_id)
            elif text == '員工管理':
                return self._handle_employee_management(user_id)
            elif text == '設定薪資':
                return self._handle_salary_setting_start(user_id)
            elif text == '請假審核':
                return self._handle_leave_approval_start(user_id)
        
        # 一般功能
        elif text in ['你好', 'hello', 'hi', 'Hello', 'Hi']:
            return self._handle_greeting(user_id)
        elif text == '功能' or text == '幫助':
            return self._handle_help(user_id)
        
        # 預設回應
        return self._handle_default_response(text)
    
    def _handle_clock_in(self, user_id):
        """處理上班打卡"""
        result = self.attendance_mgr.clock_in_out(user_id, 'clock_in')
        
        if result['success']:
            taiwan_time = datetime.now(TW_TZ)
            time_str = taiwan_time.strftime('%m/%d %H:%M')
            
            status_emoji = '✅' if result['status'] == 'normal' else '⚠️'
            
            text = f"""{status_emoji} 上班打卡成功！

📅 {time_str}
📍 {result['message']}

祝您工作順利！ 💪"""
            
            buttons = [
                {'type': 'message', 'label': '📊 查看考勤', 'text': '考勤查詢'},
                {'type': 'message', 'label': '💰 查看薪資', 'text': '薪資單'},
                {'type': 'message', 'label': '📝 申請請假', 'text': '請假申請'},
                {'type': 'message', 'label': '🏠 主選單', 'text': '你好'}
            ]
            
            quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
            return TextSendMessage(text=text, quick_reply=quick_reply)
        else:
            return TextSendMessage(text="❌ 打卡失敗，請稍後再試")
    
    def _handle_clock_out(self, user_id):
        """處理下班打卡"""
        result = self.attendance_mgr.clock_in_out(user_id, 'clock_out')
        
        if result['success']:
            taiwan_time = datetime.now(TW_TZ)
            time_str = taiwan_time.strftime('%m/%d %H:%M')
            
            status_emoji = '✅' if result['status'] == 'normal' else '⚠️'
            
            text = f"""{status_emoji} 下班打卡成功！

📅 {time_str}
📍 {result['message']}

辛苦了！明天見 👋"""
            
            buttons = [
                {'type': 'message', 'label': '📊 今日考勤', 'text': '考勤查詢'},
                {'type': 'message', 'label': '💰 查看薪資', 'text': '薪資單'},
                {'type': 'message', 'label': '🏠 主選單', 'text': '你好'}
            ]
            
            quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
            return TextSendMessage(text=text, quick_reply=quick_reply)
        else:
            return TextSendMessage(text="❌ 打卡失敗，請稍後再試")
    
    def _handle_attendance_query(self, user_id):
        """處理考勤查詢"""
        now = datetime.now(TW_TZ)
        summary = self.attendance_mgr.get_attendance_summary(user_id, now.year, now.month)
        
        text = f"""📊 {now.month}月考勤統計

🗓️ 出勤天數: {summary['total_days']}天
✅ 正常: {summary['normal_days']}天
⏰ 遲到: {summary['late_count']}次
🏃 早退: {summary['early_count']}次
⏱️ 加班: {summary['overtime_count']}次"""
        
        buttons = [
            {'type': 'message', 'label': '💰 查看薪資單', 'text': '薪資單'},
            {'type': 'message', 'label': '📋 薪資歷史', 'text': '薪資歷史'},
            {'type': 'message', 'label': '📝 申請請假', 'text': '請假申請'},
            {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
        ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        
        return TextSendMessage(text=text, quick_reply=quick_reply)
    
    def _handle_payslip_request(self, user_id):
        """處理薪資單請求"""
        now = datetime.now(TW_TZ)
        
        try:
            payroll_data = self.payroll_calc.calculate_monthly_payroll(user_id, now.year, now.month)
            
            if FLEX_AVAILABLE:
                return self._create_payslip_flex(user_id, now.year, now.month, payroll_data)
            else:
                return self._create_payslip_text(user_id, now.year, now.month, payroll_data)
                
        except Exception as e:
            print(f"薪資計算錯誤: {e}")
            return TextSendMessage(text="❌ 薪資計算暫時無法使用，請稍後再試")
    
    def _handle_payroll_history(self, user_id):
        """處理薪資歷史查詢"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT period_year, period_month, net_salary, gross_salary, status
            FROM payroll_records 
            WHERE user_id = ? 
            ORDER BY period_year DESC, period_month DESC 
            LIMIT 6
        ''', (user_id,))
        
        records = cursor.fetchall()
        conn.close()
        
        if not records:
            text = "📋 目前沒有薪資記錄"
            buttons = [
                {'type': 'message', 'label': '💰 查看本月薪資', 'text': '薪資單'},
                {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
            ]
        else:
            text = "📋 薪資歷史記錄\n" + "─" * 25 + "\n"
            
            for year, month, net_salary, gross_salary, status in records:
                status_emoji = "💰" if status == "paid" else "📝"
                text += f"{status_emoji} {year}年{month}月\n"
                text += f"   實領: ${int(net_salary):,}\n"
                text += f"   總額: ${int(gross_salary):,}\n\n"
            
            buttons = [
                {'type': 'message', 'label': '💰 查看本月薪資', 'text': '薪資單'},
                {'type': 'message', 'label': '📊 考勤統計', 'text': '考勤查詢'},
                {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
            ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        return TextSendMessage(text=text, quick_reply=quick_reply)
    
    def _handle_leave_application_start(self, user_id):
        """處理請假申請開始"""
        # 取得請假類型
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, type_name, is_paid FROM leave_types WHERE status = "active"')
        leave_types = cursor.fetchall()
        conn.close()
        
        if not leave_types:
            return TextSendMessage(text="❌ 目前沒有可用的請假類型")
        
        # 設定用戶狀態為選擇請假類型
        self.state_mgr.set_user_state(user_id, 'leave_type_selection', {'leave_types': leave_types})
        
        text = "📝 請假申請\n\n請選擇請假類型："
        
        # 創建請假類型按鈕
        buttons = []
        for type_id, type_name, is_paid in leave_types:
            paid_text = "💰" if is_paid else "⭕"
            buttons.append({
                'type': 'postback',
                'label': f'{paid_text} {type_name}',
                'data': f'leave_type_{type_id}',
                'text': f'選擇{type_name}'
            })
        
        # 添加取消按鈕
        buttons.append({'type': 'message', 'label': '❌ 取消申請', 'text': '取消'})
        
        # 如果按鈕太多，使用 Flex Message
        if FLEX_AVAILABLE and len(buttons) > 8:
            return self._create_leave_types_flex(leave_types)
        else:
            quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
            return TextSendMessage(text=text, quick_reply=quick_reply)
    
    def _create_leave_types_flex(self, leave_types):
        """創建請假類型 Flex Message"""
        if not FLEX_AVAILABLE:
            return TextSendMessage(text="請假類型選項過多，請聯繫管理員")
        
        # 創建按鈕
        buttons = []
        for type_id, type_name, is_paid in leave_types:
            paid_text = "💰有薪" if is_paid else "⭕無薪"
            buttons.append(ButtonComponent(
                action=PostbackAction(
                    label=f'{type_name} ({paid_text})',
                    data=f'leave_type_{type_id}',
                    text=f'選擇{type_name}'
                ),
                style='primary',
                color='#1DB446'
            ))
        
        # 添加取消按鈕
        buttons.append(ButtonComponent(
            action=MessageAction(label='❌ 取消申請', text='取消'),
            style='secondary',
            color='#666666'
        ))
        
        bubble = BubbleContainer(
            body=BoxComponent(
                layout="vertical",
                contents=[
                    TextComponent(
                        text="📝 請假申請",
                        weight="bold",
                        size="xl",
                        align="center",
                        color="#1DB446"
                    ),
                    TextComponent(
                        text="請選擇請假類型",
                        size="md",
                        align="center",
                        margin="md",
                        color="#666666"
                    )
                ] + buttons
            )
        )
        
        return FlexMessage(alt_text="請假申請", contents=bubble)
    
    def _handle_leave_type_selection(self, user_id, text):
        """處理請假類型選擇"""
        try:
            selection = int(text)
            user_state = self.state_mgr.get_user_state(user_id)
            leave_types = user_state['data']['leave_types']
            
            if 1 <= selection <= len(leave_types):
                selected_type = leave_types[selection - 1]
                type_id, type_name, is_paid = selected_type
                
                # 更新狀態為輸入請假日期
                self.state_mgr.set_user_state(user_id, 'leave_date_input', {
                    'leave_type_id': type_id,
                    'leave_type_name': type_name,
                    'is_paid': is_paid
                })
                
                paid_text = "💰有薪假" if is_paid else "⭕無薪假"
                
                return TextSendMessage(text=f"""✅ 已選擇：{type_name} ({paid_text})

📅 請輸入請假日期：

格式範例：
• 單日：2024-07-15
• 多日：2024-07-15~2024-07-17
• 半天：2024-07-15 上午 或 2024-07-15 下午

請輸入日期或「取消」結束申請""")
            else:
                return TextSendMessage(text="❌ 選擇無效，請輸入 1-{} 之間的數字".format(len(leave_types)))
                
        except ValueError:
            return TextSendMessage(text="❌ 請輸入正確的數字選項")
    
    def _handle_leave_date_input(self, user_id, text):
        """處理請假日期輸入"""
        try:
            user_state = self.state_mgr.get_user_state(user_id)
            leave_data = user_state['data']
            
            # 解析日期輸入
            date_info = self._parse_leave_date(text)
            
            if not date_info:
                text = """❌ 日期格式錯誤

請使用以下格式：
• 單日：2024-07-15
• 多日：2024-07-15~2024-07-17  
• 半天：2024-07-15 上午 或 2024-07-15 下午"""
                
                buttons = [
                    {'type': 'message', 'label': '📅 今天', 'text': datetime.now().strftime('%Y-%m-%d')},
                    {'type': 'message', 'label': '📅 明天', 'text': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')},
                    {'type': 'message', 'label': '❌ 取消申請', 'text': '取消'}
                ]
                
                quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
                return TextSendMessage(text=text, quick_reply=quick_reply)
            
            # 更新狀態為輸入請假原因
            leave_data.update(date_info)
            self.state_mgr.set_user_state(user_id, 'leave_reason_input', leave_data)
            
            # 顯示請假摘要
            summary = f"""📋 請假資訊確認

請假類型：{leave_data['leave_type_name']}
請假日期：{date_info['start_date']}"""
            
            if date_info['end_date'] != date_info['start_date']:
                summary += f" ~ {date_info['end_date']}"
            
            if date_info.get('period'):
                summary += f" ({date_info['period']})"
            
            summary += f"\n請假時數：{date_info['total_hours']}小時"
            summary += "\n\n📝 請輸入請假原因："
            
            buttons = [
                {'type': 'message', 'label': '🏥 身體不適', 'text': '身體不適需要休息'},
                {'type': 'message', 'label': '👨‍👩‍👧‍👦 家庭事務', 'text': '處理家庭事務'},
                {'type': 'message', 'label': '🏖️ 個人休假', 'text': '個人休假安排'},
                {'type': 'message', 'label': '❌ 重新選擇日期', 'text': '重新選擇'}
            ]
            
            quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
            return TextSendMessage(text=summary, quick_reply=quick_reply)
            
        except Exception as e:
            return TextSendMessage(text="❌ 處理日期時發生錯誤，請重新輸入")
    
    def _handle_leave_reason_input(self, user_id, text):
        """處理請假原因輸入"""
        try:
            # 處理重新選擇日期的情況
            if text == '重新選擇':
                user_state = self.state_mgr.get_user_state(user_id)
                leave_data = user_state['data']
                
                # 回到日期輸入狀態
                self.state_mgr.set_user_state(user_id, 'leave_date_input', {
                    'leave_type_id': leave_data['leave_type_id'],
                    'leave_type_name': leave_data['leave_type_name'],
                    'is_paid': leave_data['is_paid']
                })
                
                paid_text = "💰有薪假" if leave_data['is_paid'] else "⭕無薪假"
                
                text = f"""✅ 已選擇：{leave_data['leave_type_name']} ({paid_text})

📅 請重新輸入請假日期："""
                
                buttons = [
                    {'type': 'message', 'label': '📅 今天', 'text': datetime.now().strftime('%Y-%m-%d')},
                    {'type': 'message', 'label': '📅 明天', 'text': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')},
                    {'type': 'message', 'label': '❌ 取消申請', 'text': '取消'}
                ]
                
                quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
                return TextSendMessage(text=text, quick_reply=quick_reply)
            
            user_state = self.state_mgr.get_user_state(user_id)
            leave_data = user_state['data']
            
            # 提交請假申請
            result = self.leave_mgr.apply_leave(
                user_id=user_id,
                leave_type_id=leave_data['leave_type_id'],
                start_date=leave_data['start_date'],
                end_date=leave_data['end_date'],
                reason=text,
                start_time=leave_data.get('start_time'),
                end_time=leave_data.get('end_time')
            )
            
            # 清除用戶狀態
            self.state_mgr.clear_user_state(user_id)
            
            if result['success']:
                text = f"""✅ 請假申請已提交成功！

申請編號：#{result['application_id']}
請假類型：{leave_data['leave_type_name']}
請假時間：{leave_data['start_date']} ~ {leave_data['end_date']}
請假時數：{leave_data['total_hours']}小時
申請原因：{text}

狀態：⏳ 待主管審核"""
                
                buttons = [
                    {'type': 'message', 'label': '📄 查看請假記錄', 'text': '請假查詢'},
                    {'type': 'message', 'label': '📝 再申請一個', 'text': '請假申請'},
                    {'type': 'message', 'label': '📊 查看考勤', 'text': '考勤查詢'},
                    {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
                ]
                
                quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
                return TextSendMessage(text=text, quick_reply=quick_reply)
            else:
                text = f"❌ 請假申請失敗：{result.get('error', '未知錯誤')}"
                
                buttons = [
                    {'type': 'message', 'label': '🔄 重新申請', 'text': '請假申請'},
                    {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
                ]
                
                quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
                return TextSendMessage(text=text, quick_reply=quick_reply)
                
        except Exception as e:
            self.state_mgr.clear_user_state(user_id)
            return TextSendMessage(text="❌ 提交請假申請時發生錯誤，請稍後再試")
    
    def _parse_leave_date(self, text):
        """解析請假日期輸入"""
        try:
            text = text.strip()
            
            # 檢查是否有時間期間標示
            period = None
            if '上午' in text:
                period = '上午'
                text = text.replace('上午', '').strip()
            elif '下午' in text:
                period = '下午'
                text = text.replace('下午', '').strip()
            
            # 解析日期範圍
            if '~' in text:
                # 多日請假
                start_str, end_str = text.split('~')
                start_date = datetime.strptime(start_str.strip(), '%Y-%m-%d').date()
                end_date = datetime.strptime(end_str.strip(), '%Y-%m-%d').date()
            else:
                # 單日請假
                start_date = datetime.strptime(text, '%Y-%m-%d').date()
                end_date = start_date
            
            # 計算時數
            if period:
                # 半天假
                total_hours = 4.0
                if period == '上午':
                    start_time = datetime.strptime('09:00', '%H:%M').time()
                    end_time = datetime.strptime('13:00', '%H:%M').time()
                else:  # 下午
                    start_time = datetime.strptime('13:00', '%H:%M').time()
                    end_time = datetime.strptime('17:00', '%H:%M').time()
            else:
                # 全天假
                days = (end_date - start_date).days + 1
                total_hours = days * 8.0
                start_time = None
                end_time = None
            
            return {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'start_time': start_time.strftime('%H:%M') if start_time else None,
                'end_time': end_time.strftime('%H:%M') if end_time else None,
                'total_hours': total_hours,
                'period': period
            }
            
        except:
            return None
    
    def _handle_leave_query(self, user_id):
        """處理請假查詢"""
        applications = self.leave_mgr.get_leave_applications(user_id=user_id, limit=5)
        
        if not applications:
            text = "📋 目前沒有請假記錄"
            buttons = [
                {'type': 'message', 'label': '📝 申請請假', 'text': '請假申請'},
                {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
            ]
        else:
            text = "📋 請假記錄\n" + "─" * 20 + "\n"
            
            for app in applications:
                status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(app['status'], "📝")
                text += f"{status_emoji} {app['leave_type']}\n"
                text += f"   {app['start_date']} ~ {app['end_date']}\n"
                text += f"   {app['total_hours']}小時\n\n"
            
            buttons = [
                {'type': 'message', 'label': '📝 申請新的請假', 'text': '請假申請'},
                {'type': 'message', 'label': '📊 查看考勤', 'text': '考勤查詢'},
                {'type': 'message', 'label': '💰 查看薪資', 'text': '薪資單'},
                {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
            ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        return TextSendMessage(text=text, quick_reply=quick_reply)
    
    def _handle_salary_setting_start(self, user_id):
        """處理薪資設定開始"""
        if not (self.perm.has_permission(user_id, 'all') or self.perm.has_permission(user_id, 'payroll')):
            return TextSendMessage(text="❌ 您沒有權限執行此操作")
        
        # 取得員工清單
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, name, employee_id 
            FROM users 
            WHERE status = 'active' 
            ORDER BY employee_id
        ''')
        
        employees = cursor.fetchall()
        conn.close()
        
        if not employees:
            return TextSendMessage(text="❌ 目前沒有員工資料")
        
        # 設定狀態為選擇員工
        self.state_mgr.set_user_state(user_id, 'admin_employee_selection', {
            'employees': employees,
            'action': 'salary_setting'
        })
        
        text = "👥 請選擇要設定薪資的員工：\n\n"
        for i, (emp_user_id, name, employee_id) in enumerate(employees, 1):
            text += f"{i}. {name} ({employee_id})\n"
        
        text += "\n請回覆數字選擇，例如：1\n或輸入「取消」結束操作"
        
        return TextSendMessage(text=text)
    
    def _handle_admin_employee_selection(self, user_id, text):
        """處理管理員員工選擇"""
        try:
            selection = int(text)
            user_state = self.state_mgr.get_user_state(user_id)
            employees = user_state['data']['employees']
            action = user_state['data']['action']
            
            if 1 <= selection <= len(employees):
                selected_employee = employees[selection - 1]
                emp_user_id, emp_name, employee_id = selected_employee
                
                if action == 'salary_setting':
                    # 進入薪資設定流程
                    self.state_mgr.set_user_state(user_id, 'salary_setting', {
                        'target_user_id': emp_user_id,
                        'target_name': emp_name,
                        'target_employee_id': employee_id,
                        'step': 'base_salary'
                    })
                    
                    return TextSendMessage(text=f"""💰 設定 {emp_name} ({employee_id}) 的薪資

步驟 1/6：基本薪資
請輸入基本月薪（元），若為時薪制請輸入 0：

範例：30000 或 0

請輸入金額或「取消」結束設定""")
                
                elif action == 'employee_info':
                    # 顯示員工詳細資訊
                    employee_info = self.user_mgr.get_user_info(emp_user_id)
                    roles = self.perm.get_user_roles(emp_user_id)
                    
                    self.state_mgr.clear_user_state(user_id)
                    
                    role_names = ', '.join([role['name'] for role in roles]) if roles else '無'
                    
                    return TextSendMessage(text=f"""👤 員工資訊

姓名：{employee_info['name']}
員工編號：{employee_info['employee_id']}
部門：{employee_info['department']}
職位：{employee_info['position'] or '未設定'}
到職日：{employee_info['hire_date'] or '未設定'}
角色：{role_names}
狀態：{employee_info['status']}

需要其他操作請重新選擇功能""")
                
            else:
                return TextSendMessage(text=f"❌ 選擇無效，請輸入 1-{len(employees)} 之間的數字")
                
        except ValueError:
            return TextSendMessage(text="❌ 請輸入正確的數字選項")
    
    def _handle_salary_setting(self, user_id, text):
        """處理薪資設定流程"""
        try:
            user_state = self.state_mgr.get_user_state(user_id)
            salary_data = user_state['data']
            current_step = salary_data['step']
            
            if current_step == 'base_salary':
                base_salary = float(text)
                salary_data['base_salary'] = base_salary
                salary_data['step'] = 'hourly_rate'
                
                self.state_mgr.set_user_state(user_id, 'salary_setting', salary_data)
                
                return TextSendMessage(text=f"""步驟 2/6：時薪設定
請輸入時薪（元）：

範例：183

請輸入時薪或「取消」結束設定""")
            
            elif current_step == 'hourly_rate':
                hourly_rate = float(text)
                salary_data['hourly_rate'] = hourly_rate
                salary_data['step'] = 'allowances'
                
                self.state_mgr.set_user_state(user_id, 'salary_setting', salary_data)
                
                return TextSendMessage(text=f"""步驟 3/6：津貼設定
請輸入各項津貼（元），用逗號分隔：

格式：職務津貼,交通津貼,餐費津貼,住房津貼
範例：5000,2000,3000,0

請輸入津貼或「取消」結束設定""")
            
            elif current_step == 'allowances':
                allowances = [float(x.strip()) for x in text.split(',')]
                if len(allowances) >= 4:
                    salary_data['position_allowance'] = allowances[0]
                    salary_data['transport_allowance'] = allowances[1] 
                    salary_data['meal_allowance'] = allowances[2]
                    salary_data['housing_allowance'] = allowances[3]
                    salary_data['step'] = 'confirm'
                    
                    self.state_mgr.set_user_state(user_id, 'salary_setting', salary_data)
                    
                    # 顯示設定摘要
                    summary = f"""📋 薪資設定確認

員工：{salary_data['target_name']} ({salary_data['target_employee_id']})

💰 薪資結構：
基本月薪：${int(salary_data['base_salary']):,}
時薪：${int(salary_data['hourly_rate']):,}

🎁 津貼項目：
職務津貼：${int(salary_data['position_allowance']):,}
交通津貼：${int(salary_data['transport_allowance']):,}
餐費津貼：${int(salary_data['meal_allowance']):,}
住房津貼：${int(salary_data['housing_allowance']):,}

請確認設定並回覆：
• 確認 - 儲存設定
• 取消 - 放棄設定"""
                    
                    return TextSendMessage(text=summary)
                else:
                    return TextSendMessage(text="❌ 請輸入4個津貼金額，用逗號分隔")
            
            elif current_step == 'confirm':
                if text == '確認':
                    # 儲存薪資設定
                    salary_structure = {
                        'base_salary': salary_data['base_salary'],
                        'hourly_rate': salary_data['hourly_rate'],
                        'position_allowance': salary_data['position_allowance'],
                        'transport_allowance': salary_data['transport_allowance'],
                        'meal_allowance': salary_data['meal_allowance'],
                        'housing_allowance': salary_data['housing_allowance'],
                        'overtime_rate': 1.33,
                        'holiday_rate': 2.0
                    }
                    
                    # 儲存到資料庫
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    
                    cursor.execute('''
                        INSERT INTO salary_structures (
                            user_id, base_salary, hourly_rate, overtime_rate, holiday_rate,
                            position_allowance, transport_allowance, meal_allowance, housing_allowance,
                            effective_date, created_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, DATE('now'), ?)
                    ''', (
                        salary_data['target_user_id'], salary_data['base_salary'], 
                        salary_data['hourly_rate'], 1.33, 2.0,
                        salary_data['position_allowance'], salary_data['transport_allowance'],
                        salary_data['meal_allowance'], salary_data['housing_allowance'], user_id
                    ))
                    
                    conn.commit()
                    conn.close()
                    
                    # 清除狀態
                    self.state_mgr.clear_user_state(user_id)
                    
                    return TextSendMessage(text=f"""✅ 薪資設定完成！

{salary_data['target_name']} 的薪資結構已更新
生效日期：{datetime.now().strftime('%Y-%m-%d')}

員工可透過「薪資單」查看最新薪資資訊""")
                else:
                    return TextSendMessage(text="❌ 請回覆「確認」或「取消」")
                    
        except ValueError:
            return TextSendMessage(text="❌ 請輸入正確的數字格式")
        except Exception as e:
            self.state_mgr.clear_user_state(user_id)
            return TextSendMessage(text="❌ 設定過程發生錯誤，請重新開始")
    
    def _handle_leave_approval_start(self, user_id):
        """處理請假審核開始"""
        if not (self.perm.has_permission(user_id, 'all') or self.perm.has_permission(user_id, 'approve')):
            return TextSendMessage(text="❌ 您沒有權限執行此操作")
        
        # 取得待審核的請假申請
        pending_applications = self.leave_mgr.get_leave_applications(status='pending', limit=10)
        
        if not pending_applications:
            return TextSendMessage(text="📋 目前沒有待審核的請假申請")
        
        # 設定狀態為選擇請假申請
        self.state_mgr.set_user_state(user_id, 'leave_approval_selection', {
            'applications': pending_applications
        })
        
        text = "📋 待審核請假申請：\n\n"
        for i, app in enumerate(pending_applications, 1):
            text += f"{i}. {app['user_name']} - {app['leave_type']}\n"
            text += f"   {app['start_date']} ~ {app['end_date']} ({app['total_hours']}小時)\n"
            text += f"   申請時間：{app['application_date'][:16]}\n\n"
        
        text += "請回覆數字選擇要審核的申請，例如：1\n或輸入「取消」結束審核"
        
        return TextSendMessage(text=text)
    
    def _handle_leave_approval_selection(self, user_id, text):
        """處理請假審核選擇"""
        try:
            selection = int(text)
            user_state = self.state_mgr.get_user_state(user_id)
            applications = user_state['data']['applications']
            
            if 1 <= selection <= len(applications):
                selected_app = applications[selection - 1]
                
                # 設定狀態為審核決定
                self.state_mgr.set_user_state(user_id, 'leave_approval_decision', {
                    'application': selected_app
                })
                
                app = selected_app
                summary = f"""📋 請假申請詳情

申請人：{app['user_name']}
請假類型：{app['leave_type']}
請假時間：{app['start_date']} ~ {app['end_date']}
請假時數：{app['total_hours']}小時
申請原因：{app['reason']}
申請時間：{app['application_date'][:16]}

請選擇審核結果：
• 同意 - 核准請假
• 拒絕 - 駁回申請
• 取消 - 結束審核"""
                
                return TextSendMessage(text=summary)
            else:
                return TextSendMessage(text=f"❌ 選擇無效，請輸入 1-{len(applications)} 之間的數字")
                
        except ValueError:
            return TextSendMessage(text="❌ 請輸入正確的數字選項")
    
    def _handle_leave_approval_decision(self, user_id, text):
        """處理請假審核決定"""
        user_state = self.state_mgr.get_user_state(user_id)
        application = user_state['data']['application']
        
        app = application
        summary = f"""📋 請假申請詳情

申請人：{app['user_name']}
請假類型：{app['leave_type']}
請假時間：{app['start_date']} ~ {app['end_date']}
請假時數：{app['total_hours']}小時
申請原因：{app['reason']}
申請時間：{app['application_date'][:16]}

請選擇審核結果："""
        
        buttons = [
            {'type': 'postback', 'label': '✅ 同意', 'data': f'approve_leave_{app["id"]}_yes', 'text': '同意請假'},
            {'type': 'postback', 'label': '❌ 拒絕', 'data': f'approve_leave_{app["id"]}_no', 'text': '拒絕請假'},
            {'type': 'message', 'label': '🔙 返回審核列表', 'text': '請假審核'},
            {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
        ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        return TextSendMessage(text=summary, quick_reply=quick_reply)
    
    def _handle_leave_approval_reject_reason(self, user_id, text):
        """處理請假拒絕原因輸入"""
        user_state = self.state_mgr.get_user_state(user_id)
        application_id = user_state['data']['application_id']
        
        # 駁回請假申請
        success = self.leave_mgr.approve_leave(
            application_id=application_id,
            approved_by=user_id,
            approved=False,
            reject_reason=text
        )
        
        self.state_mgr.clear_user_state(user_id)
        
        if success:
            response_text = f"""❌ 請假申請已駁回

駁回原因：{text}

系統將自動通知申請人"""
            
            buttons = [
                {'type': 'message', 'label': '📋 繼續審核', 'text': '請假審核'},
                {'type': 'message', 'label': '🔧 管理功能', 'text': '管理員功能'},
                {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
            ]
            
            quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
            return TextSendMessage(text=response_text, quick_reply=quick_reply)
        else:
            return TextSendMessage(text="❌ 駁回操作失敗，請稍後再試")
    
    def handle_postback_event(self, user_id, postback_data):
        """處理 Postback 事件"""
        # 確保用戶存在
        self.user_mgr.create_or_get_user(user_id)
        
        # 解析 postback 數據
        if postback_data.startswith('leave_type_'):
            return self._handle_leave_type_postback(user_id, postback_data)
        elif postback_data.startswith('approve_leave_'):
            return self._handle_leave_approval_postback(user_id, postback_data)
        elif postback_data.startswith('employee_'):
            return self._handle_employee_postback(user_id, postback_data)
        else:
            return TextSendMessage(text="❌ 未知的操作")
    
    def _handle_leave_type_postback(self, user_id, postback_data):
        """處理請假類型選擇的 Postback"""
        try:
            # 解析 leave_type_ID
            type_id = int(postback_data.split('_')[2])
            
            user_state = self.state_mgr.get_user_state(user_id)
            leave_types = user_state['data']['leave_types']
            
            # 找到選中的請假類型
            selected_type = None
            for leave_type in leave_types:
                if leave_type[0] == type_id:
                    selected_type = leave_type
                    break
            
            if not selected_type:
                return TextSendMessage(text="❌ 選擇的請假類型無效")
            
            type_id, type_name, is_paid = selected_type
            
            # 更新狀態為輸入請假日期
            self.state_mgr.set_user_state(user_id, 'leave_date_input', {
                'leave_type_id': type_id,
                'leave_type_name': type_name,
                'is_paid': is_paid
            })
            
            paid_text = "💰有薪假" if is_paid else "⭕無薪假"
            
            text = f"""✅ 已選擇：{type_name} ({paid_text})

📅 請輸入請假日期：

格式範例：
• 單日：2024-07-15
• 多日：2024-07-15~2024-07-17
• 半天：2024-07-15 上午 或 2024-07-15 下午"""
            
            buttons = [
                {'type': 'message', 'label': '📅 今天請假', 'text': datetime.now().strftime('%Y-%m-%d')},
                {'type': 'message', 'label': '📅 明天請假', 'text': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')},
                {'type': 'message', 'label': '📅 後天請假', 'text': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')},
                {'type': 'message', 'label': '❌ 取消申請', 'text': '取消'}
            ]
            
            quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
            return TextSendMessage(text=text, quick_reply=quick_reply)
            
        except (ValueError, IndexError):
            return TextSendMessage(text="❌ 處理請假類型時發生錯誤")
    
    def _handle_leave_approval_postback(self, user_id, postback_data):
        """處理請假審核的 Postback"""
        try:
            # 解析 approve_leave_ID_decision
            parts = postback_data.split('_')
            application_id = int(parts[2])
            decision = parts[3]  # yes 或 no
            
            if decision == 'yes':
                # 核准請假
                success = self.leave_mgr.approve_leave(
                    application_id=application_id,
                    approved_by=user_id,
                    approved=True
                )
                
                self.state_mgr.clear_user_state(user_id)
                
                if success:
                    text = """✅ 請假申請已核准

系統將自動通知申請人"""
                    
                    buttons = [
                        {'type': 'message', 'label': '📋 繼續審核', 'text': '請假審核'},
                        {'type': 'message', 'label': '🔧 管理功能', 'text': '管理員功能'},
                        {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
                    ]
                    
                    quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
                    return TextSendMessage(text=text, quick_reply=quick_reply)
                else:
                    return TextSendMessage(text="❌ 核准失敗，請稍後再試")
                    
            elif decision == 'no':
                # 進入拒絕原因輸入狀態
                self.state_mgr.set_user_state(user_id, 'leave_approval_reject_reason', {
                    'application_id': application_id
                })
                
                text = "📝 請輸入拒絕原因："
                
                buttons = [
                    {'type': 'message', 'label': '⏰ 時間衝突', 'text': '該時段已有其他員工請假'},
                    {'type': 'message', 'label': '🏢 業務需要', 'text': '業務繁忙需要人力支援'},
                    {'type': 'message', 'label': '📋 資料不足', 'text': '請假資料不完整'},
                    {'type': 'message', 'label': '❌ 取消審核', 'text': '取消'}
                ]
                
                quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
                return TextSendMessage(text=text, quick_reply=quick_reply)
                
    def _handle_employee_postback(self, user_id, postback_data):
        """處理員工相關的 Postback"""
        # 這個方法可以後續擴展
        return TextSendMessage(text="👥 員工功能開發中...")
    
    def _handle_payroll_statistics(self, user_id):
        """處理薪資統計"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # 本月統計
        current_year = datetime.now().year
        current_month = datetime.now().month
        
        cursor.execute('''
            SELECT COUNT(*), SUM(gross_salary), SUM(net_salary), AVG(total_work_hours)
            FROM payroll_records 
            WHERE period_year = ? AND period_month = ?
        ''', (current_year, current_month))
        
        stats = cursor.fetchone()
        conn.close()
        
        if stats and stats[0] > 0:
            text = f"""📊 {current_month}月薪資統計

👥 計薪人數: {stats[0]}人
💰 薪資總額: ${int(stats[1]):,}
💵 實發總額: ${int(stats[2]):,}
⏰ 平均工時: {stats[3]:.1f}小時"""
        else:
            text = f"📊 {current_month}月尚無薪資記錄"
        
        buttons = [
            {'type': 'message', 'label': '👥 員工管理', 'text': '員工管理'},
            {'type': 'message', 'label': '💰 設定薪資', 'text': '設定薪資'},
            {'type': 'message', 'label': '📋 請假審核', 'text': '請假審核'},
            {'type': 'message', 'label': '🔧 管理功能', 'text': '管理員功能'},
            {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
        ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        return TextSendMessage(text=text, quick_reply=quick_reply)
    
    def _handle_employee_management(self, user_id):
        """處理員工管理"""
        if not (self.perm.has_permission(user_id, 'all') or self.perm.has_permission(user_id, 'payroll')):
            return TextSendMessage(text="❌ 您沒有權限執行此操作")
        
        # 取得員工清單
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active
            FROM users
        ''')
        
        stats = cursor.fetchone()
        
        cursor.execute('''
            SELECT user_id, name, employee_id, status
            FROM users 
            ORDER BY employee_id
            LIMIT 10
        ''')
        
        employees = cursor.fetchall()
        conn.close()
        
        # 設定狀態為選擇員工
        self.state_mgr.set_user_state(user_id, 'admin_employee_selection', {
            'employees': employees,
            'action': 'employee_info'
        })
        
        text = f"""👥 員工管理

總員工數: {stats[0]}人
在職員工: {stats[1]}人
離職員工: {stats[0] - stats[1]}人

選擇要查看的員工：
"""
        
        for i, (emp_user_id, name, employee_id, status) in enumerate(employees, 1):
            status_emoji = "✅" if status == "active" else "❌"
            text += f"{i}. {name} ({employee_id}) {status_emoji}\n"
        
        text += "\n請回覆數字選擇，例如：1\n或輸入「取消」結束查看"
        
        return TextSendMessage(text=text)
    
    def _handle_greeting(self, user_id):
        """處理問候"""
        user_info = self.user_mgr.get_user_info(user_id)
        user_name = user_info['name'] if user_info else '您'
        permissions = self.perm.get_user_permissions(user_id)
        
        text = f"""👋 {user_name}，歡迎使用薪資管理系統！

請選擇您要使用的功能："""

        # 基本功能按鈕
        buttons = [
            {'type': 'message', 'label': '🕘 上班打卡', 'text': '上班'},
            {'type': 'message', 'label': '🏃 下班打卡', 'text': '下班'},
            {'type': 'message', 'label': '📊 考勤查詢', 'text': '考勤查詢'},
            {'type': 'message', 'label': '💰 薪資單', 'text': '薪資單'},
            {'type': 'message', 'label': '📋 薪資歷史', 'text': '薪資歷史'},
            {'type': 'message', 'label': '📝 請假申請', 'text': '請假申請'},
            {'type': 'message', 'label': '📄 請假查詢', 'text': '請假查詢'},
        ]
        
        # 管理員按鈕
        if permissions.get('all') or permissions.get('payroll'):
            buttons.append({'type': 'message', 'label': '🔧 管理員功能', 'text': '管理員功能'})
        
        buttons.append({'type': 'message', 'label': '❓ 功能說明', 'text': '功能'})
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        
        return TextSendMessage(text=text, quick_reply=quick_reply)
    
    def _handle_help(self, user_id):
        """處理幫助"""
        permissions = self.perm.get_user_permissions(user_id)
        
        text = """🔧 系統功能說明

👤 個人功能：
• 考勤管理 - 上下班打卡、查詢統計
• 薪資查詢 - 薪資單、歷史記錄
• 請假管理 - 申請請假、查詢記錄

💼 企業功能：
• 自動工時計算
• 薪資結構管理
• 扣款項目計算
• 請假審核流程"""

        if permissions.get('all') or permissions.get('payroll'):
            text += "\n\n🔧 管理功能：\n• 員工管理\n• 薪資統計\n• 系統設定"
        
        buttons = [
            {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'},
            {'type': 'message', 'label': '🕘 開始打卡', 'text': '上班'},
            {'type': 'message', 'label': '💰 查看薪資', 'text': '薪資單'},
        ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        
        return TextSendMessage(text=text, quick_reply=quick_reply)
    
    def _handle_default_response(self, text):
        """處理預設回應"""
        response_text = f"""收到訊息：{text}

💡 常用功能："""
        
        buttons = [
            {'type': 'message', 'label': '🕘 上班打卡', 'text': '上班'},
            {'type': 'message', 'label': '🏃 下班打卡', 'text': '下班'},
            {'type': 'message', 'label': '📊 考勤查詢', 'text': '考勤查詢'},
            {'type': 'message', 'label': '💰 薪資單', 'text': '薪資單'},
            {'type': 'message', 'label': '📝 請假申請', 'text': '請假申請'},
            {'type': 'message', 'label': '❓ 完整功能', 'text': '功能'},
            {'type': 'message', 'label': '🏠 主選單', 'text': '你好'}
        ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        return TextSendMessage(text=response_text, quick_reply=quick_reply)
    
    def _create_payslip_text(self, user_id, year, month, payroll_data):
        """創建文字版薪資單"""
        user_info = self.user_mgr.get_user_info(user_id)
        user_name = user_info['name'] if user_info else "員工"
        
        work_data = payroll_data['work_data']
        calc = payroll_data['calculations']
        deductions = payroll_data['deduction_details']
        
        text = f"""💰 薪資單
{year}年{month}月
員工：{user_name}

📊 工時統計
─────────────────
工作天數: {work_data['work_days']}天
總工時: {work_data['total_hours']}小時
正常工時: {work_data['regular_hours']}小時
加班工時: {work_data['overtime_hours']}小時

💵 薪資明細
─────────────────
基本薪資: ${int(calc['base_salary']):,}
加班費: ${int(calc['overtime_pay']):,}
津貼: ${int(calc['total_allowances']):,}
薪資總額: ${int(calc['gross_salary']):,}

📉 扣款項目
─────────────────
勞保費: ${int(deductions['labor_insurance']):,}
健保費: ${int(deductions['health_insurance']):,}
退休金: ${int(deductions['pension']):,}
所得稅: ${int(deductions['income_tax']):,}
扣款總額: ${int(deductions['total_deductions']):,}

💰 實領薪資
─────────────────
${int(payroll_data['net_salary']):,}"""
        
        buttons = [
            {'type': 'message', 'label': '📋 薪資歷史', 'text': '薪資歷史'},
            {'type': 'message', 'label': '📊 考勤統計', 'text': '考勤查詢'},
            {'type': 'message', 'label': '📝 申請請假', 'text': '請假申請'},
            {'type': 'message', 'label': '🏠 返回主選單', 'text': '你好'}
        ]
        
        quick_reply = self.button_helper.create_quick_reply_buttons(buttons)
        return TextSendMessage(text=text, quick_reply=quick_reply)

# 全域變量初始化
db_manager = DatabaseManager()
permission_manager = PermissionManager(db_manager)
message_handler = LineMessageHandler(db_manager, permission_manager)

# LINE Bot Webhook 處理
@app.route("/callback", methods=['POST'])
def callback():
    """LINE Bot Webhook 回調處理"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

# 訊息事件處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理文字訊息"""
    try:
        user_id = event.source.user_id
        message_text = event.message.text
        
        print(f"📱 收到訊息: {message_text} from {user_id}")
        
        response = message_handler.handle_text_message(user_id, message_text)
        
        line_bot_api.reply_message(event.reply_token, response)
    
    except Exception as e:
        print(f"❌ 處理訊息時發生錯誤: {e}")
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ 系統暫時繁忙，請稍後再試")
            )
        except:
            pass

# Postback 事件處理
@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件"""
    try:
        user_id = event.source.user_id
        postback_data = event.postback.data
        
        print(f"📱 收到 Postback: {postback_data} from {user_id}")
        
        response = message_handler.handle_postback_event(user_id, postback_data)
        
        line_bot_api.reply_message(event.reply_token, response)
    
    except Exception as e:
        print(f"❌ 處理 Postback 時發生錯誤: {e}")
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ 系統暫時繁忙，請稍後再試")
            )
        except:
            pass
# 用戶加入事件處理
@handler.add(FollowEvent)
def handle_follow(event):
    """處理用戶加入事件"""
    user_id = event.source.user_id
    
    # 創建用戶記錄
    message_handler.user_mgr.create_or_get_user(user_id)
    
    welcome_message = """🎉 歡迎加入薪資管理系統！

💼 這是一個完整的企業薪資解決方案

✨ 主要功能：
📊 智能考勤管理
💵 自動薪資計算  
📋 請假申請審核
📱 即時薪資查詢
📈 統計報表分析

請選擇功能開始使用："""
    
    # 創建歡迎按鈕
    buttons = [
        {'type': 'message', 'label': '🕘 上班打卡', 'text': '上班'},
        {'type': 'message', 'label': '💰 查看薪資', 'text': '薪資單'},
        {'type': 'message', 'label': '📝 申請請假', 'text': '請假申請'},
        {'type': 'message', 'label': '📊 查看考勤', 'text': '考勤查詢'},
        {'type': 'message', 'label': '❓ 功能說明', 'text': '功能'},
        {'type': 'message', 'label': '🏠 主選單', 'text': '你好'}
    ]
    
    quick_reply = message_handler.button_helper.create_quick_reply_buttons(buttons)
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_message, quick_reply=quick_reply)
    )

# Web API 路由
@app.route('/api/users/<user_id>/payroll')
def get_user_payroll_api(user_id):
    """API: 取得用戶薪資"""
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    try:
        payroll_calc = PayrollCalculator(db_manager, permission_manager)
        payroll_data = payroll_calc.calculate_monthly_payroll(user_id, year, month)
        
        return jsonify({
            'success': True,
            'data': payroll_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/attendance/summary')
def get_attendance_summary_api():
    """API: 取得考勤統計"""
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT u.name, u.employee_id,
               COUNT(DISTINCT ar.record_date) as work_days,
               SUM(CASE WHEN ar.status = 'late' THEN 1 ELSE 0 END) as late_count
        FROM users u
        LEFT JOIN attendance_records ar ON u.user_id = ar.user_id 
        WHERE strftime('%Y', ar.record_date) = ? AND strftime('%m', ar.record_date) = ?
        GROUP BY u.user_id
    ''', (str(year), f"{month:02d}"))
    
    results = cursor.fetchall()
    conn.close()
    
    summary = []
    for row in results:
        summary.append({
            'name': row[0],
            'employee_id': row[1],
            'work_days': row[2],
            'late_count': row[3]
        })
    
    return jsonify(summary)

@app.route('/api/leaves/pending')
def get_pending_leaves_api():
    """API: 取得待審核請假"""
    leave_mgr = LeaveManager(db_manager, permission_manager)
    applications = leave_mgr.get_leave_applications(status='pending', limit=20)
    
    return jsonify(applications)

@app.route('/api/system/stats')
def get_system_stats_api():
    """API: 取得系統統計"""
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    
    # 員工統計
    cursor.execute('SELECT COUNT(*) FROM users WHERE status = "active"')
    active_users = cursor.fetchone()[0]
    
    # 本月考勤統計
    current_month = datetime.now().strftime('%Y-%m')
    cursor.execute('''
        SELECT COUNT(DISTINCT user_id) 
        FROM attendance_records 
        WHERE strftime('%Y-%m', record_date) = ?
    ''', (current_month,))
    
    monthly_attendance = cursor.fetchone()[0]
    
    # 待審核請假
    cursor.execute('SELECT COUNT(*) FROM leave_applications WHERE status = "pending"')
    pending_leaves = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'active_employees': active_users,
        'monthly_attendance': monthly_attendance,
        'pending_leaves': pending_leaves,
        'system_status': 'running'
    })

# 管理後台路由
@app.route('/admin')
def admin_dashboard():
    """管理員後台"""
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>薪資管理系統 - 管理後台</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Microsoft JhengHei', Arial, sans-serif; background: #f5f5f5; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; }
        .container { max-width: 1200px; margin: 20px auto; padding: 0 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }
        .card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .card h3 { color: #333; margin-bottom: 15px; }
        .stat { font-size: 2em; font-weight: bold; color: #667eea; }
        .btn { background: #667eea; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; margin: 5px; }
        .btn:hover { background: #5a6fd8; }
        .table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .table th, .table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .table th { background: #f8f9fa; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🏢 薪資管理系統 - 管理後台</h1>
        <p>企業級人力資源管理解決方案</p>
    </div>
    
    <div class="container">
        <div class="grid">
            <div class="card">
                <h3>📊 系統統計</h3>
                <div id="stats">載入中...</div>
            </div>
            
            <div class="card">
                <h3>🔧 快速功能</h3>
                <a href="/api/system/stats" class="btn">系統狀態</a>
                <a href="/api/attendance/summary" class="btn">考勤統計</a>
                <a href="/api/leaves/pending" class="btn">待審請假</a>
            </div>
            
            <div class="card">
                <h3>📱 LINE Bot 功能</h3>
                <p>✅ Webhook 已設定</p>
                <p>✅ 用戶管理已啟用</p>
                <p>✅ 權限控制已啟用</p>
                <p>✅ 薪資計算已啟用</p>
            </div>
        </div>
        
        <div class="card">
            <h3>📋 最新活動</h3>
            <div id="activities">載入中...</div>
        </div>
    </div>
    
    <script>
        // 載入統計數據
        fetch('/api/system/stats')
            .then(response => response.json())
            .then(data => {
                document.getElementById('stats').innerHTML = `
                    <p>👥 在職員工: <span class="stat">${data.active_employees}</span></p>
                    <p>📊 本月出勤: <span class="stat">${data.monthly_attendance}</span></p>
                    <p>⏳ 待審請假: <span class="stat">${data.pending_leaves}</span></p>
                `;
            })
            .catch(error => {
                document.getElementById('stats').innerHTML = '<p>❌ 載入失敗</p>';
            });
            
        // 載入活動記錄
        document.getElementById('activities').innerHTML = `
            <table class="table">
                <tr><th>時間</th><th>用戶</th><th>操作</th><th>狀態</th></tr>
                <tr><td>剛剛</td><td>系統</td><td>系統啟動</td><td>✅</td></tr>
                <tr><td>剛剛</td><td>系統</td><td>資料庫初始化</td><td>✅</td></tr>
                <tr><td>剛剛</td><td>系統</td><td>LINE Bot 設定</td><td>✅</td></tr>
            </table>
        `;
    </script>
</body>
</html>
    ''')

# Flask 首頁路由
@app.route('/')
def home():
    """系統首頁"""
    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>企業薪資管理系統</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Microsoft JhengHei', Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; min-height: 100vh; }
        .container { max-width: 1200px; margin: 0 auto; padding: 40px 20px; }
        .hero { text-align: center; margin-bottom: 60px; }
        .hero h1 { font-size: 3em; margin-bottom: 20px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
        .hero p { font-size: 1.2em; opacity: 0.9; }
        .features { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px; margin: 40px 0; }
        .feature { background: rgba(255,255,255,0.1); padding: 30px; border-radius: 15px; backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.2); }
        .feature h3 { font-size: 1.5em; margin-bottom: 15px; }
        .feature p { opacity: 0.9; line-height: 1.6; }
        .status { background: rgba(255,255,255,0.2); padding: 30px; border-radius: 15px; margin: 40px 0; }
        .status h3 { margin-bottom: 20px; }
        .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .status-item { background: rgba(255,255,255,0.1); padding: 20px; border-radius: 10px; text-align: center; }
        .status-item .value { font-size: 2em; font-weight: bold; margin-bottom: 10px; }
        .links { text-align: center; margin: 40px 0; }
        .btn { background: rgba(255,255,255,0.2); color: white; padding: 15px 30px; border: 2px solid rgba(255,255,255,0.3); border-radius: 10px; text-decoration: none; margin: 10px; display: inline-block; transition: all 0.3s; }
        .btn:hover { background: rgba(255,255,255,0.3); transform: translateY(-2px); }
    </style>
</head>
<body>
    <div class="container">
        <div class="hero">
            <h1>🏢 企業薪資管理系統</h1>
            <p>完整的人力資源管理解決方案，整合考勤、薪資、請假等功能</p>
        </div>
        
        <div class="features">
            <div class="feature">
                <h3>📊 智能考勤管理</h3>
                <p>自動化打卡系統，即時統計工時，支援遲到早退判斷，完整的考勤報表分析</p>
            </div>
            
            <div class="feature">
                <h3>💰 精準薪資計算</h3>
                <p>靈活的薪資結構設定，自動計算加班費，智能扣款項目處理，一鍵生成薪資單</p>
            </div>
            
            <div class="feature">
                <h3>📝 請假流程管理</h3>
                <p>線上請假申請，多層級審核機制，自動計算剩餘假期，請假記錄完整追蹤</p>
            </div>
            
            <div class="feature">
                <h3>👥 權限角色控制</h3>
                <p>完整的權限管理體系，管理員、HR、主管、員工分級管理，確保資料安全</p>
            </div>
            
            <div class="feature">
                <h3>📱 LINE Bot 整合</h3>
                <p>便捷的手機操作介面，即時通知推送，隨時隨地查詢個人資料，提升使用體驗</p>
            </div>
            
            <div class="feature">
                <h3>📈 統計報表分析</h3>
                <p>豐富的數據分析功能，視覺化報表展示，協助管理層進行決策分析</p>
            </div>
        </div>
        
        <div class="status">
            <h3>🚀 系統狀態</h3>
            <div class="status-grid" id="systemStatus">
                <div class="status-item">
                    <div class="value">✅</div>
                    <div>資料庫</div>
                </div>
                <div class="status-item">
                    <div class="value">✅</div>
                    <div>LINE Bot</div>
                </div>
                <div class="status-item">
                    <div class="value">✅</div>
                    <div>API 服務</div>
                </div>
                <div class="status-item">
                    <div class="value">✅</div>
                    <div>權限管理</div>
                </div>
            </div>
        </div>
        
        <div class="links">
            <a href="/admin" class="btn">🔧 管理後台</a>
            <a href="/api/system/stats" class="btn">📊 系統統計</a>
            <a href="/callback" class="btn">🔗 Webhook 測試</a>
        </div>
        
        <div style="text-align: center; margin-top: 40px; opacity: 0.8;">
            <p>Webhook URL: <code>{{ request.url_root }}callback</code></p>
            <p>管理員可透過 LINE Bot 輸入「管理員功能」存取管理選單</p>
        </div>
    </div>
</body>
</html>
    ''')

if __name__ == "__main__":
    print("🚀 啟動完整薪資管理系統...")
    print("✅ 資料庫初始化完成")
    print("✅ 權限管理系統已啟用")
    print("✅ 考勤管理功能已就緒")
    print("✅ 薪資計算引擎已就緒")
    print("✅ 請假管理功能已就緒")
    print("✅ LINE Bot 整合已完成")
    print("✅ 按鈕式操作介面已啟用")
    print("✅ Web API 已啟用")
    print("✅ 管理後台已啟用")
    
    if FLEX_AVAILABLE:
        print("✅ Flex Message 支援已啟用")
    else:
        print("✅ Quick Reply 按鈕支援已啟用")
    
    port = int(os.environ.get('PORT', 5011))
    print(f"🌐 系統啟動於 http://localhost:{port}")
    print(f"🔗 Webhook URL: http://localhost:{port}/callback")
    print(f"🔧 管理後台: http://localhost:{port}/admin")
    print("💼 準備為企業提供完整薪資解決方案！")
    print("\n📱 支援的按鈕操作：")
    print("   🕘 一鍵打卡 - 快速上下班")
    print("   📝 按鈕請假 - 無需手動輸入")
    print("   💰 薪資查詢 - 便捷操作")
    print("   🔧 管理功能 - 直覺式管理")
    
    app.run(host='0.0.0.0', port=port, debug=False)