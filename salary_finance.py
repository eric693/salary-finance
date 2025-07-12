# payroll_system.py - 修正後的完整薪資計算系統
from flask import Flask, request, abort, render_template_string, jsonify
import sqlite3
import os
from datetime import datetime, timedelta
import pytz
import calendar
import json
from decimal import Decimal, ROUND_HALF_UP

# LINE Bot SDK v2 - 修正導入問題
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError

# 基本訊息模型
from linebot.models import (
    MessageEvent, TextMessage, FollowEvent, TextSendMessage,
    PostbackEvent, PostbackAction, MessageAction, URIAction
)

# Flex Message 相關導入 - 修正版本
try:
    # 嘗試新版本的導入方式
    from linebot.models.flex_message import (
        FlexSendMessage as FlexMessage,
        BubbleContainer, BoxComponent, TextComponent, ButtonComponent
    )
except ImportError:
    try:
        # 嘗試舊版本的導入方式
        from linebot.models import (
            FlexSendMessage as FlexMessage,
            BubbleContainer, BoxComponent, TextComponent, ButtonComponent
        )
    except ImportError:
        # 如果都失敗，使用基本訊息
        print("⚠️  Flex Message 不可用，將使用基本文字訊息")
        FlexMessage = None
        BubbleContainer = None
        BoxComponent = None
        TextComponent = None
        ButtonComponent = None

# 繼承原有的 Flask 應用
app = Flask(__name__)

# LINE Bot 設定
ACCESS_TOKEN = 'MzGhqH9h1ZKP2zwU2+NY+IAqpHxYbCDSAHMKzqcK5bOi5MWWll4/gU7fFy09f7tW5jhq7wmPAE+XzqO1Mqkc7oE/RPI6a0IgYfSFYJAGfB81OU5PjOdYGa4O4dfV34VMsw9NPqK5id7SGqoDXvObcgdB04t89/1O/w1cDnyilFU='
WEBHOOK_SECRET = '389db7eda4b80b0d28086cdc15ae5ec1'

line_bot_api = LineBotApi(ACCESS_TOKEN)
handler = WebhookHandler(WEBHOOK_SECRET)

# 台灣時區設定
TW_TZ = pytz.timezone('Asia/Taipei')

# 初始化用戶管理
def init_user_management():
    """初始化用戶管理資料表"""
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # 用戶表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE,
            name TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 考勤記錄表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            action_type TEXT,
            taiwan_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# 用戶管理功能
def create_or_get_user(user_id):
    """創建或取得用戶"""
    try:
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        # 確保表存在
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE,
                name TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action_type TEXT,
                taiwan_time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # 檢查用戶是否存在
        cursor.execute('SELECT id, name FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            # 創建新用戶
            try:
                # 嘗試取得用戶資訊
                profile = line_bot_api.get_profile(user_id)
                user_name = profile.display_name
            except:
                user_name = f"用戶{user_id[-4:]}"
            
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)
            ''', (user_id, user_name))
            
            conn.commit()
            print(f"✅ 新用戶已創建: {user_name} ({user_id})")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 創建用戶時發生錯誤: {e}")
        if 'conn' in locals():
            conn.close()
        return False

# 初始化薪資相關資料庫
def init_payroll_db():
    """初始化薪資計算相關資料表"""
    try:
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        # 用戶表 (確保存在)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE,
                name TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 考勤記錄表 (確保存在)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action_type TEXT,
                taiwan_time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # 薪資結構表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS salary_structures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                base_salary REAL DEFAULT 0,          -- 基本薪資
                hourly_rate REAL DEFAULT 0,          -- 時薪
                overtime_rate REAL DEFAULT 1.33,     -- 加班費率 (1.33倍)
                holiday_rate REAL DEFAULT 2.0,       -- 假日加班費率 (2倍)
                position_allowance REAL DEFAULT 0,   -- 職務加給
                transport_allowance REAL DEFAULT 0,  -- 交通津貼
                meal_allowance REAL DEFAULT 0,       -- 餐費津貼
                other_allowances REAL DEFAULT 0,     -- 其他津貼
                effective_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # 薪資扣款表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS salary_deductions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                labor_insurance REAL DEFAULT 0,      -- 勞保費
                health_insurance REAL DEFAULT 0,     -- 健保費
                income_tax REAL DEFAULT 0,           -- 所得稅
                pension REAL DEFAULT 0,              -- 退休金提撥
                other_deductions REAL DEFAULT 0,     -- 其他扣款
                effective_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # 薪資計算記錄表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payroll_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                period_year INTEGER,
                period_month INTEGER,
                total_work_hours REAL DEFAULT 0,     -- 總工作時數
                regular_hours REAL DEFAULT 0,        -- 正常工時
                overtime_hours REAL DEFAULT 0,       -- 加班時數
                holiday_hours REAL DEFAULT 0,        -- 假日工時
                work_days INTEGER DEFAULT 0,         -- 工作天數
                base_salary REAL DEFAULT 0,          -- 基本薪資
                overtime_pay REAL DEFAULT 0,         -- 加班費
                holiday_pay REAL DEFAULT 0,          -- 假日加班費
                allowances REAL DEFAULT 0,           -- 津貼總額
                gross_salary REAL DEFAULT 0,         -- 薪資總額
                total_deductions REAL DEFAULT 0,     -- 扣款總額
                net_salary REAL DEFAULT 0,           -- 實領薪資
                status TEXT DEFAULT 'draft',         -- 狀態: draft, confirmed, paid
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                paid_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # 薪資明細表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payroll_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payroll_record_id INTEGER,
                item_type TEXT,                       -- 項目類型: salary, allowance, deduction
                item_name TEXT,                       -- 項目名稱
                amount REAL,                          -- 金額
                calculation_base TEXT,                -- 計算基準
                notes TEXT,                           -- 備註
                FOREIGN KEY (payroll_record_id) REFERENCES payroll_records (id)
            )
        ''')
        
        # 薪資設定表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payroll_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE,
                setting_value TEXT,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 插入預設設定
        default_settings = [
            ('standard_work_hours', '8', '標準工作時數/天'),
            ('monthly_work_days', '22', '每月標準工作天數'),
            ('overtime_threshold', '8', '加班門檻時數'),
            ('labor_insurance_rate', '0.105', '勞保費率'),
            ('health_insurance_rate', '0.0517', '健保費率'),
            ('pension_rate', '0.06', '退休金提撥率'),
            ('income_tax_threshold', '40000', '所得稅起徵點')
        ]
        
        for key, value, desc in default_settings:
            cursor.execute('''
                INSERT OR IGNORE INTO payroll_settings (setting_key, setting_value, description)
                VALUES (?, ?, ?)
            ''', (key, value, desc))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 初始化薪資資料庫時發生錯誤: {e}")
        return False

# 薪資計算引擎
class PayrollCalculator:
    def __init__(self):
        try:
            self.conn = sqlite3.connect('attendance.db')
            self.cursor = self.conn.cursor()
            # 確保必要的表存在
            self._ensure_tables_exist()
        except Exception as e:
            print(f"❌ 薪資計算器初始化失敗: {e}")
            self.conn = None
            self.cursor = None
    
    def _ensure_tables_exist(self):
        """確保所有必要的表都存在"""
        try:
            # 確保薪資設定表存在
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS payroll_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    setting_key TEXT UNIQUE,
                    setting_value TEXT,
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 確保用戶表存在
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE,
                    name TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 確保考勤記錄表存在
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    action_type TEXT,
                    taiwan_time TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            self.conn.commit()
        except Exception as e:
            print(f"❌ 確保表存在時發生錯誤: {e}")
    
    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
    
    def get_setting(self, key, default=0):
        """取得系統設定值"""
        if not self.cursor:
            return default
            
        try:
            self.cursor.execute('SELECT setting_value FROM payroll_settings WHERE setting_key = ?', (key,))
            result = self.cursor.fetchone()
            if result:
                try:
                    return float(result[0])
                except:
                    return result[0]
        except Exception as e:
            print(f"❌ 取得設定值時發生錯誤: {e}")
        
        return default
    
    def get_user_salary_structure(self, user_id):
        """取得用戶薪資結構"""
        self.cursor.execute('''
            SELECT base_salary, hourly_rate, overtime_rate, holiday_rate,
                   position_allowance, transport_allowance, meal_allowance, other_allowances
            FROM salary_structures 
            WHERE user_id = ? 
            ORDER BY effective_date DESC LIMIT 1
        ''', (user_id,))
        
        result = self.cursor.fetchone()
        if result:
            return {
                'base_salary': result[0] or 0,
                'hourly_rate': result[1] or 0,
                'overtime_rate': result[2] or 1.33,
                'holiday_rate': result[3] or 2.0,
                'position_allowance': result[4] or 0,
                'transport_allowance': result[5] or 0,
                'meal_allowance': result[6] or 0,
                'other_allowances': result[7] or 0
            }
        
        # 預設值
        return {
            'base_salary': 0,
            'hourly_rate': 183,  # 台灣基本工資時薪
            'overtime_rate': 1.33,
            'holiday_rate': 2.0,
            'position_allowance': 0,
            'transport_allowance': 0,
            'meal_allowance': 0,
            'other_allowances': 0
        }
    
    def get_user_deductions(self, user_id):
        """取得用戶扣款設定"""
        self.cursor.execute('''
            SELECT labor_insurance, health_insurance, income_tax, pension, other_deductions
            FROM salary_deductions 
            WHERE user_id = ? 
            ORDER BY effective_date DESC LIMIT 1
        ''', (user_id,))
        
        result = self.cursor.fetchone()
        if result:
            return {
                'labor_insurance': result[0] or 0,
                'health_insurance': result[1] or 0,
                'income_tax': result[2] or 0,
                'pension': result[3] or 0,
                'other_deductions': result[4] or 0
            }
        
        return {
            'labor_insurance': 0,
            'health_insurance': 0,
            'income_tax': 0,
            'pension': 0,
            'other_deductions': 0
        }
    
    def calculate_work_hours(self, user_id, year, month):
        """計算指定月份的工作時數"""
        # 取得該月份的所有打卡記錄
        self.cursor.execute('''
            SELECT action_type, taiwan_time, DATE(taiwan_time) as work_date
            FROM attendance_records 
            WHERE user_id = ? AND strftime('%Y', taiwan_time) = ? AND strftime('%m', taiwan_time) = ?
            ORDER BY taiwan_time
        ''', (user_id, str(year), f"{month:02d}"))
        
        records = self.cursor.fetchall()
        
        # 按日期分組計算工時
        daily_hours = {}
        work_days = set()
        
        current_date = None
        clock_in_time = None
        
        for action_type, time_str, work_date in records:
            if work_date != current_date:
                current_date = work_date
                clock_in_time = None
            
            time_obj = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            
            if action_type == '上班':
                clock_in_time = time_obj
                work_days.add(work_date)
            elif action_type == '下班' and clock_in_time:
                # 計算當日工時
                work_hours = (time_obj - clock_in_time).total_seconds() / 3600
                daily_hours[work_date] = daily_hours.get(work_date, 0) + work_hours
                clock_in_time = None
        
        # 統計總工時
        total_hours = sum(daily_hours.values())
        standard_hours = self.get_setting('standard_work_hours', 8)
        
        # 計算正常工時和加班工時
        regular_hours = 0
        overtime_hours = 0
        
        for date, hours in daily_hours.items():
            if hours <= standard_hours:
                regular_hours += hours
            else:
                regular_hours += standard_hours
                overtime_hours += (hours - standard_hours)
        
        return {
            'total_hours': round(total_hours, 2),
            'regular_hours': round(regular_hours, 2),
            'overtime_hours': round(overtime_hours, 2),
            'work_days': len(work_days),
            'daily_hours': daily_hours
        }
    
    def calculate_monthly_payroll(self, user_id, year, month):
        """計算指定月份的薪資"""
        
        # 取得工時資料
        work_data = self.calculate_work_hours(user_id, year, month)
        
        # 取得薪資結構
        salary_structure = self.get_user_salary_structure(user_id)
        
        # 取得扣款設定
        deductions = self.get_user_deductions(user_id)
        
        # 計算薪資組成
        calculations = {}
        
        # 基本薪資計算
        if salary_structure['base_salary'] > 0:
            # 月薪制
            base_salary = salary_structure['base_salary']
        else:
            # 時薪制
            base_salary = work_data['regular_hours'] * salary_structure['hourly_rate']
        
        calculations['base_salary'] = round(base_salary, 0)
        
        # 加班費計算
        overtime_pay = work_data['overtime_hours'] * salary_structure['hourly_rate'] * salary_structure['overtime_rate']
        calculations['overtime_pay'] = round(overtime_pay, 0)
        
        # 假日加班費 (暫時設為0，可後續擴充)
        calculations['holiday_pay'] = 0
        
        # 津貼計算
        allowances = (salary_structure['position_allowance'] + 
                     salary_structure['transport_allowance'] + 
                     salary_structure['meal_allowance'] + 
                     salary_structure['other_allowances'])
        calculations['allowances'] = round(allowances, 0)
        
        # 薪資總額
        gross_salary = (calculations['base_salary'] + 
                       calculations['overtime_pay'] + 
                       calculations['holiday_pay'] + 
                       calculations['allowances'])
        calculations['gross_salary'] = round(gross_salary, 0)
        
        # 扣款計算
        if deductions['labor_insurance'] == 0:
            # 自動計算勞保費 (以薪資總額計算)
            labor_insurance_rate = self.get_setting('labor_insurance_rate', 0.105)
            labor_insurance = gross_salary * labor_insurance_rate * 0.2  # 員工負擔20%
        else:
            labor_insurance = deductions['labor_insurance']
        
        if deductions['health_insurance'] == 0:
            # 自動計算健保費
            health_insurance_rate = self.get_setting('health_insurance_rate', 0.0517)
            health_insurance = gross_salary * health_insurance_rate * 0.3  # 員工負擔30%
        else:
            health_insurance = deductions['health_insurance']
        
        if deductions['pension'] == 0:
            # 自動計算退休金提撥
            pension_rate = self.get_setting('pension_rate', 0.06)
            pension = gross_salary * pension_rate
        else:
            pension = deductions['pension']
        
        # 所得稅計算 (簡化版)
        income_tax_threshold = self.get_setting('income_tax_threshold', 40000)
        if gross_salary > income_tax_threshold and deductions['income_tax'] == 0:
            income_tax = (gross_salary - income_tax_threshold) * 0.05  # 簡化稅率5%
        else:
            income_tax = deductions['income_tax']
        
        total_deductions = (labor_insurance + health_insurance + 
                           pension + income_tax + deductions['other_deductions'])
        calculations['total_deductions'] = round(total_deductions, 0)
        
        # 實領薪資
        net_salary = gross_salary - total_deductions
        calculations['net_salary'] = round(net_salary, 0)
        
        # 詳細扣款項目
        calculations['deduction_details'] = {
            'labor_insurance': round(labor_insurance, 0),
            'health_insurance': round(health_insurance, 0),
            'pension': round(pension, 0),
            'income_tax': round(income_tax, 0),
            'other_deductions': round(deductions['other_deductions'], 0)
        }
        
        return {
            'work_data': work_data,
            'calculations': calculations,
            'salary_structure': salary_structure
        }
    
    def save_payroll_record(self, user_id, year, month, payroll_data):
        """儲存薪資計算記錄"""
        work_data = payroll_data['work_data']
        calc = payroll_data['calculations']
        
        # 檢查是否已存在記錄
        self.cursor.execute('''
            SELECT id FROM payroll_records 
            WHERE user_id = ? AND period_year = ? AND period_month = ?
        ''', (user_id, year, month))
        
        existing = self.cursor.fetchone()
        
        if existing:
            # 更新現有記錄
            self.cursor.execute('''
                UPDATE payroll_records SET
                    total_work_hours = ?, regular_hours = ?, overtime_hours = ?,
                    work_days = ?, base_salary = ?, overtime_pay = ?, holiday_pay = ?,
                    allowances = ?, gross_salary = ?, total_deductions = ?, net_salary = ?,
                    calculated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                work_data['total_hours'], work_data['regular_hours'], work_data['overtime_hours'],
                work_data['work_days'], calc['base_salary'], calc['overtime_pay'], calc['holiday_pay'],
                calc['allowances'], calc['gross_salary'], calc['total_deductions'], calc['net_salary'],
                existing[0]
            ))
            record_id = existing[0]
        else:
            # 新增記錄
            self.cursor.execute('''
                INSERT INTO payroll_records (
                    user_id, period_year, period_month, total_work_hours, regular_hours, 
                    overtime_hours, work_days, base_salary, overtime_pay, holiday_pay,
                    allowances, gross_salary, total_deductions, net_salary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, year, month, work_data['total_hours'], work_data['regular_hours'],
                work_data['overtime_hours'], work_data['work_days'], calc['base_salary'],
                calc['overtime_pay'], calc['holiday_pay'], calc['allowances'],
                calc['gross_salary'], calc['total_deductions'], calc['net_salary']
            ))
            record_id = self.cursor.lastrowid
        
        # 清除舊的明細記錄
        self.cursor.execute('DELETE FROM payroll_details WHERE payroll_record_id = ?', (record_id,))
        
        # 新增薪資明細
        details = [
            ('salary', '基本薪資', calc['base_salary'], f"工時: {work_data['regular_hours']}小時"),
            ('salary', '加班費', calc['overtime_pay'], f"加班: {work_data['overtime_hours']}小時"),
            ('allowance', '各項津貼', calc['allowances'], '津貼總計'),
            ('deduction', '勞保費', calc['deduction_details']['labor_insurance'], '員工負擔部分'),
            ('deduction', '健保費', calc['deduction_details']['health_insurance'], '員工負擔部分'),
            ('deduction', '退休金', calc['deduction_details']['pension'], '6%提撥'),
            ('deduction', '所得稅', calc['deduction_details']['income_tax'], '預扣稅額'),
            ('deduction', '其他扣款', calc['deduction_details']['other_deductions'], '其他項目')
        ]
        
        for item_type, item_name, amount, notes in details:
            if amount > 0:  # 只記錄有金額的項目
                self.cursor.execute('''
                    INSERT INTO payroll_details (payroll_record_id, item_type, item_name, amount, notes)
                    VALUES (?, ?, ?, ?, ?)
                ''', (record_id, item_type, item_name, amount, notes))
        
        self.conn.commit()
        return record_id

# 薪資管理類
class PayrollManager:
    def __init__(self):
        self.calculator = PayrollCalculator()
        self.line_bot_api = line_bot_api
    
    def set_user_salary_structure(self, user_id, salary_data):
        """設定用戶薪資結構"""
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO salary_structures (
                user_id, base_salary, hourly_rate, overtime_rate, holiday_rate,
                position_allowance, transport_allowance, meal_allowance, other_allowances,
                effective_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, DATE('now'))
        ''', (
            user_id, salary_data.get('base_salary', 0), salary_data.get('hourly_rate', 183),
            salary_data.get('overtime_rate', 1.33), salary_data.get('holiday_rate', 2.0),
            salary_data.get('position_allowance', 0), salary_data.get('transport_allowance', 0),
            salary_data.get('meal_allowance', 0), salary_data.get('other_allowances', 0)
        ))
        
        conn.commit()
        conn.close()
    
    def calculate_and_save_payroll(self, user_id, year=None, month=None):
        """計算並儲存薪資"""
        if not year or not month:
            now = datetime.now(TW_TZ)
            year = year or now.year
            month = month or now.month
        
        # 計算薪資
        payroll_data = self.calculator.calculate_monthly_payroll(user_id, year, month)
        
        # 儲存記錄
        record_id = self.calculator.save_payroll_record(user_id, year, month, payroll_data)
        
        return record_id, payroll_data
    
    def generate_payslip_message(self, user_id, year, month):
        """生成薪資單訊息"""
        # 計算薪資
        record_id, payroll_data = self.calculate_and_save_payroll(user_id, year, month)
        
        work_data = payroll_data['work_data']
        calc = payroll_data['calculations']
        
        # 如果 Flex Message 可用，生成 Flex Message
        if FlexMessage and BubbleContainer:
            payslip = self.create_payslip_flex(user_id, year, month, work_data, calc)
        else:
            # 否則生成文字訊息
            payslip = self.create_payslip_text(user_id, year, month, work_data, calc)
        
        return payslip
    
    def create_payslip_text(self, user_id, year, month, work_data, calculations):
        """創建文字版薪資單"""
        
        # 取得用戶名稱
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM users WHERE user_id = ?', (user_id,))
        user_result = cursor.fetchone()
        user_name = user_result[0] if user_result else "員工"
        conn.close()
        
        payslip_text = f"""💰 薪資單
{year}年{month}月
員工：{user_name}

📊 工時統計
─────────────────
工作天數: {work_data['work_days']}天
正常工時: {work_data['regular_hours']}小時
加班工時: {work_data['overtime_hours']}小時

💵 薪資明細
─────────────────
基本薪資: ${int(calculations['base_salary']):,}
加班費: ${int(calculations['overtime_pay']):,}
津貼: ${int(calculations['allowances']):,}
薪資總額: ${int(calculations['gross_salary']):,}

📉 扣款項目
─────────────────
勞健保費: ${int(calculations['deduction_details']['labor_insurance'] + calculations['deduction_details']['health_insurance']):,}
退休金提撥: ${int(calculations['deduction_details']['pension']):,}
所得稅: ${int(calculations['deduction_details']['income_tax']):,}
扣款總額: ${int(calculations['total_deductions']):,}

💰 實領薪資
─────────────────
${int(calculations['net_salary']):,}

回覆「薪資歷史」查看歷史記錄
回覆「薪資統計」查看年度統計"""
        
        return TextSendMessage(text=payslip_text)
    
    def create_payslip_flex(self, user_id, year, month, work_data, calculations):
        """創建Flex Message薪資單"""
        
        # 取得用戶名稱
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM users WHERE user_id = ?', (user_id,))
        user_result = cursor.fetchone()
        user_name = user_result[0] if user_result else "員工"
        conn.close()
        
        bubble = BubbleContainer(
            body=BoxComponent(
                layout="vertical",
                contents=[
                    # 標題
                    TextComponent(
                        text="💰 薪資單",
                        weight="bold",
                        size="xl",
                        align="center",
                        color="#1DB446"
                    ),
                    TextComponent(
                        text=f"{year}年{month}月",
                        size="md",
                        align="center",
                        color="#666666",
                        margin="sm"
                    ),
                    TextComponent(
                        text=f"員工：{user_name}",
                        size="sm",
                        color="#666666",
                        margin="md"
                    ),
                    
                    # 工時資訊
                    BoxComponent(
                        layout="vertical",
                        margin="lg",
                        spacing="sm",
                        contents=[
                            TextComponent(
                                text="📊 工時統計",
                                weight="bold",
                                color="#333333"
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="工作天數", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"{work_data['work_days']}天", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="正常工時", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"{work_data['regular_hours']}小時", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="加班工時", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"{work_data['overtime_hours']}小時", size="sm", align="end", flex=1)
                                ]
                            )
                        ]
                    ),
                    
                    # 薪資明細
                    BoxComponent(
                        layout="vertical",
                        margin="lg",
                        spacing="sm",
                        contents=[
                            TextComponent(
                                text="💵 薪資明細",
                                weight="bold",
                                color="#333333"
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="基本薪資", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"${int(calculations['base_salary']):,}", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="加班費", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"${int(calculations['overtime_pay']):,}", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="津貼", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"${int(calculations['allowances']):,}", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="薪資總額", size="sm", weight="bold", color="#333333", flex=2),
                                    TextComponent(text=f"${int(calculations['gross_salary']):,}", size="sm", weight="bold", align="end", flex=1)
                                ]
                            )
                        ]
                    ),
                    
                    # 扣款明細
                    BoxComponent(
                        layout="vertical",
                        margin="lg",
                        spacing="sm",
                        contents=[
                            TextComponent(
                                text="📉 扣款項目",
                                weight="bold",
                                color="#333333"
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="勞健保費", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"${int(calculations['deduction_details']['labor_insurance'] + calculations['deduction_details']['health_insurance']):,}", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="退休金提撥", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"${int(calculations['deduction_details']['pension']):,}", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="所得稅", size="sm", color="#666666", flex=2),
                                    TextComponent(text=f"${int(calculations['deduction_details']['income_tax']):,}", size="sm", align="end", flex=1)
                                ]
                            ),
                            BoxComponent(
                                layout="baseline",
                                spacing="sm",
                                contents=[
                                    TextComponent(text="扣款總額", size="sm", weight="bold", color="#333333", flex=2),
                                    TextComponent(text=f"${int(calculations['total_deductions']):,}", size="sm", weight="bold", align="end", flex=1)
                                ]
                            )
                        ]
                    ),
                    
                    # 實領薪資
                    BoxComponent(
                        layout="baseline",
                        margin="lg",
                        padding="md",
                        backgroundColor="#E8F5E8",
                        cornerRadius="md",
                        contents=[
                            TextComponent(
                                text="💰 實領薪資",
                                size="lg",
                                weight="bold",
                                color="#1DB446",
                                flex=2
                            ),
                            TextComponent(
                                text=f"${int(calculations['net_salary']):,}",
                                size="lg",
                                weight="bold",
                                color="#1DB446",
                                align="end",
                                flex=1
                            )
                        ]
                    )
                ]
            ),
            footer=BoxComponent(
                layout="vertical",
                spacing="sm",
                contents=[
                    ButtonComponent(
                        style="primary",
                        action=PostbackAction(label="📊 查看詳細", data=f"payroll_detail_{year}_{month}"),
                        color="#1DB446"
                    ),
                    ButtonComponent(
                        style="secondary",
                        action=MessageAction(label="📋 薪資歷史", text="薪資歷史")
                    )
                ]
            )
        )
        
        return FlexMessage(alt_text=f"{year}年{month}月薪資單", contents=bubble)
    
    def get_payroll_history(self, user_id, limit=6):
        """取得薪資歷史記錄"""
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT period_year, period_month, net_salary, gross_salary, total_work_hours, status
            FROM payroll_records 
            WHERE user_id = ? 
            ORDER BY period_year DESC, period_month DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        records = cursor.fetchall()
        conn.close()
        
        if not records:
            return TextSendMessage(text="📋 目前沒有薪資記錄")
        
        history_text = "📋 薪資歷史記錄\n" + "─" * 25 + "\n"
        
        for year, month, net_salary, gross_salary, work_hours, status in records:
            status_emoji = "✅" if status == "paid" else "📝" if status == "confirmed" else "📄"
            history_text += f"{status_emoji} {year}年{month}月\n"
            history_text += f"   💰 實領: ${int(net_salary):,}\n"
            history_text += f"   📊 總額: ${int(gross_salary):,}\n"
            history_text += f"   ⏰ 工時: {work_hours}小時\n\n"
        
        return TextSendMessage(text=history_text)

# 擴展訊息處理器
class PayrollMessageProcessor:
    def __init__(self):
        self.payroll_manager = PayrollManager()
        self.calculator = PayrollCalculator()
    
    def process_payroll_command(self, user_id, message_text):
        """處理薪資相關指令"""
        
        if '薪資單' in message_text or '薪水單' in message_text:
            # 生成當月薪資單
            now = datetime.now(TW_TZ)
            return self.payroll_manager.generate_payslip_message(user_id, now.year, now.month)
        
        elif '薪資歷史' in message_text or '薪水歷史' in message_text:
            # 取得薪資歷史
            return self.payroll_manager.get_payroll_history(user_id)
        
        elif '設定薪資' in message_text:
            # 薪資設定說明
            return TextSendMessage(text="""
💰 薪資設定說明

請聯繫管理員設定以下項目：
📊 基本薪資或時薪
⏰ 加班費率 (預設1.33倍)
🏖️ 假日加班費率 (預設2倍)
💼 職務加給
🚗 交通津貼
🍽️ 餐費津貼
📋 其他津貼

扣款項目會自動計算：
🏥 勞健保費
💰 退休金提撥
📋 所得稅

請輸入「聯絡管理員」取得協助。
            """)
        
        elif '薪資統計' in message_text:
            # 年度薪資統計
            return self.generate_yearly_stats(user_id)
        
        else:
            return None
    
    def generate_yearly_stats(self, user_id):
        """生成年度薪資統計"""
        current_year = datetime.now(TW_TZ).year
        
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as months_count,
                SUM(net_salary) as total_net,
                SUM(gross_salary) as total_gross,
                SUM(total_work_hours) as total_hours,
                AVG(net_salary) as avg_net
            FROM payroll_records 
            WHERE user_id = ? AND period_year = ?
        ''', (user_id, current_year))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] > 0:
            months_count, total_net, total_gross, total_hours, avg_net = result
            
            stats_text = f"📊 {current_year}年薪資統計\n"
            stats_text += "─" * 25 + "\n"
            stats_text += f"📅 計薪月份: {months_count}個月\n"
            stats_text += f"💰 總實領: ${int(total_net):,}\n"
            stats_text += f"📊 總薪資: ${int(total_gross):,}\n"
            stats_text += f"⏰ 總工時: {total_hours:.1f}小時\n"
            stats_text += f"📈 月平均: ${int(avg_net):,}\n"
            
            if total_hours > 0:
                hourly_rate = total_net / total_hours
                stats_text += f"💵 平均時薪: ${hourly_rate:.0f}\n"
            
            return TextSendMessage(text=stats_text)
        else:
            return TextSendMessage(text=f"📊 {current_year}年尚無薪資記錄")

# 管理員薪資功能
class AdminPayrollManager:
    def __init__(self):
        self.payroll_manager = PayrollManager()
    
    def set_employee_salary(self, user_id, salary_data):
        """設定員工薪資結構"""
        return self.payroll_manager.set_user_salary_structure(user_id, salary_data)
    
    def calculate_all_payroll(self, year, month):
        """計算所有員工薪資"""
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        # 取得所有員工
        cursor.execute('SELECT user_id, name FROM users WHERE status = "active"')
        employees = cursor.fetchall()
        conn.close()
        
        results = []
        for user_id, name in employees:
            try:
                record_id, payroll_data = self.payroll_manager.calculate_and_save_payroll(user_id, year, month)
                results.append({
                    'user_id': user_id,
                    'name': name,
                    'status': 'success',
                    'record_id': record_id,
                    'net_salary': payroll_data['calculations']['net_salary']
                })
            except Exception as e:
                results.append({
                    'user_id': user_id,
                    'name': name,
                    'status': 'error',
                    'error': str(e)
                })
        
        return results

# LINE Bot Webhook 處理
@app.route("/callback", methods=['POST'])
def callback():
    """LINE Bot Webhook 回調處理"""
    # 取得 X-Line-Signature header 值
    signature = request.headers['X-Line-Signature']

    # 取得 request body
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 處理 webhook body
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
        
        # 檢查是否為群組訊息
        source_type = event.source.type
        
        print(f"📱 收到訊息: {message_text} (來源: {source_type})")
        
        # 確保用戶存在
        if not create_or_get_user(user_id):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ 系統初始化中，請稍後再試...")
            )
            return
        
        # 處理薪資相關訊息
        if handle_payroll_message(event):
            return
        
        # 處理其他一般訊息
        if '你好' in message_text or 'hello' in message_text.lower() or 'hi' in message_text.lower():
            reply_text = """👋 歡迎使用薪資管理系統！

💰 可用功能：
• 薪資單 - 查看當月薪資
• 薪資歷史 - 查看歷史記錄  
• 薪資統計 - 查看年度統計
• 設定薪資 - 薪資設定說明

請輸入任一功能關鍵字開始使用！"""
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
        
        elif '功能' in message_text or '幫助' in message_text:
            reply_text = """🔧 系統功能說明

💼 薪資管理：
• 自動計算工時
• 薪資結構設定
• 自動扣款計算
• 薪資單生成

📊 統計分析：
• 工時統計
• 薪資歷史
• 年度分析

輸入「薪資單」開始使用！"""
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
        
        else:
            # 預設回應
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"收到訊息：{message_text}\n\n輸入「薪資單」查看薪資資訊，或輸入「功能」查看可用功能。")
            )
    
    except Exception as e:
        print(f"❌ 處理訊息時發生錯誤: {e}")
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
    create_or_get_user(user_id)
    
    # 歡迎訊息
    welcome_message = """🎉 歡迎加入薪資管理系統！

💰 這是一個完整的企業薪資解決方案

✨ 主要功能：
📊 自動工時計算
💵 薪資結構管理  
📋 扣款項目計算
📱 薪資單生成
📈 薪資統計分析

請輸入「薪資單」開始體驗，或輸入「功能」查看詳細說明！

如需設定薪資結構，請聯繫管理員。"""
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_message)
    )

# Flask 路由擴展
@app.route('/api/payroll/calculate/<user_id>')
def calculate_payroll_api(user_id):
    """API: 計算指定用戶薪資"""
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    try:
        payroll_manager = PayrollManager()
        record_id, payroll_data = payroll_manager.calculate_and_save_payroll(user_id, year, month)
        
        return jsonify({
            'success': True,
            'record_id': record_id,
            'payroll_data': payroll_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/payroll/history/<user_id>')
def get_payroll_history_api(user_id):
    """API: 取得薪資歷史"""
    limit = request.args.get('limit', 12, type=int)
    
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT period_year, period_month, net_salary, gross_salary, 
               total_work_hours, status, calculated_at
        FROM payroll_records 
        WHERE user_id = ? 
        ORDER BY period_year DESC, period_month DESC 
        LIMIT ?
    ''', (user_id, limit))
    
    records = cursor.fetchall()
    conn.close()
    
    history = []
    for record in records:
        history.append({
            'year': record[0],
            'month': record[1],
            'net_salary': record[2],
            'gross_salary': record[3],
            'total_hours': record[4],
            'status': record[5],
            'calculated_at': record[6]
        })
    
    return jsonify(history)

@app.route('/api/payroll/stats')
def get_payroll_stats():
    """API: 取得薪資統計"""
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # 本月薪資統計
    current_month = datetime.now().strftime('%Y-%m')
    cursor.execute('''
        SELECT COUNT(*), SUM(gross_salary), SUM(net_salary), AVG(total_work_hours)
        FROM payroll_records 
        WHERE strftime('%Y-%m', calculated_at) = ?
    ''', (current_month,))
    
    current_stats = cursor.fetchone()
    
    # 年度統計
    current_year = str(datetime.now().year)
    cursor.execute('''
        SELECT COUNT(*), SUM(gross_salary), SUM(net_salary), SUM(total_work_hours)
        FROM payroll_records 
        WHERE period_year = ?
    ''', (current_year,))
    
    yearly_stats = cursor.fetchone()
    
    conn.close()
    
    return jsonify({
        'current_month': {
            'records': current_stats[0] or 0,
            'total_gross': current_stats[1] or 0,
            'total_net': current_stats[2] or 0,
            'avg_hours': current_stats[3] or 0
        },
        'current_year': {
            'records': yearly_stats[0] or 0,
            'total_gross': yearly_stats[1] or 0,
            'total_net': yearly_stats[2] or 0,
            'total_hours': yearly_stats[3] or 0
        }
    })

# 整合到原有的訊息處理
def handle_payroll_message(event):
    """處理薪資相關訊息"""
    try:
        user_id = event.source.user_id
        message_text = event.message.text
        
        processor = PayrollMessageProcessor()
        response = processor.process_payroll_command(user_id, message_text)
        
        if response:
            line_bot_api.reply_message(event.reply_token, response)
            return True
        
        return False
    
    except Exception as e:
        print(f"❌ 處理薪資訊息時發生錯誤: {e}")
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ 薪資功能暫時無法使用，請稍後再試")
            )
        except:
            pass
        return True  # 表示已經處理過了，避免重複回應

# Postback 處理
@handler.add(PostbackEvent)
def handle_payroll_postback(event):
    """處理薪資相關Postback"""
    user_id = event.source.user_id
    data = event.postback.data
    
    if data.startswith('payroll_detail_'):
        # 薪資詳細資訊
        parts = data.split('_')
        year, month = int(parts[2]), int(parts[3])
        
        processor = PayrollMessageProcessor()
        response = processor.payroll_manager.generate_payslip_message(user_id, year, month)
        line_bot_api.reply_message(event.reply_token, response)

# Flask 首頁路由
@app.route('/')
def home():
    """首頁顯示"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>薪資管理系統</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
            .container { background: rgba(255,255,255,0.1); padding: 30px; border-radius: 15px; backdrop-filter: blur(10px); }
            h1 { color: #fff; text-align: center; margin-bottom: 30px; }
            .status { background: rgba(255,255,255,0.2); padding: 20px; border-radius: 10px; margin: 20px 0; }
            .feature { margin: 10px 0; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 8px; }
            .api-link { color: #4CAF50; text-decoration: none; font-weight: bold; }
            .api-link:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏢 企業薪資管理系統</h1>
            
            <div class="status">
                <h3>✅ 系統狀態：運行中</h3>
                <p><strong>Webhook URL:</strong> /callback</p>
                <p><strong>API 端點：</strong> 已就緒</p>
                <p><strong>資料庫：</strong> SQLite (attendance.db)</p>
            </div>
            
            <div class="status">
                <h3>💰 核心功能</h3>
                <div class="feature">📊 自動工時計算與統計</div>
                <div class="feature">💵 彈性薪資結構管理</div>
                <div class="feature">📋 智能扣款項目計算</div>
                <div class="feature">📱 即時薪資單生成</div>
                <div class="feature">📈 全面薪資統計分析</div>
                <div class="feature">🔗 LINE Bot 整合支援</div>
            </div>
            
            <div class="status">
                <h3>🔧 API 端點</h3>
                <p><a href="/api/payroll/stats" class="api-link">📊 薪資統計 API</a></p>
                <p><a href="/test" class="api-link">🧪 功能測試頁面</a></p>
                <p><strong>計算薪資：</strong> /api/payroll/calculate/{user_id}</p>
                <p><strong>薪資歷史：</strong> /api/payroll/history/{user_id}</p>
            </div>
            
            <div class="status">
                <h3>📱 LINE Bot 使用說明</h3>
                <p>• 輸入「<strong>薪資單</strong>」查看當月薪資</p>
                <p>• 輸入「<strong>薪資歷史</strong>」查看歷史記錄</p>
                <p>• 輸入「<strong>薪資統計</strong>」查看年度統計</p>
                <p>• 輸入「<strong>你好</strong>」查看所有功能</p>
            </div>
        </div>
    </body>
    </html>
    """

# 測試用戶輸入處理
@app.route('/test')
def test_payroll():
    """測試薪資功能"""
    return """
    <h2>薪資系統測試</h2>
    <p>✅ 薪資資料庫已初始化</p>
    <p>💰 薪資計算引擎就緒</p>
    <p>📊 支援功能：</p>
    <ul>
        <li>工時計算</li>
        <li>薪資結構管理</li>
        <li>自動扣款計算</li>
        <li>薪資單生成</li>
        <li>歷史記錄查詢</li>
    </ul>
    """

if __name__ == "__main__":
    print("🚀 啟動薪資計算系統...")
    
    # 初始化用戶管理
    init_user_management()
    print("✅ 用戶管理系統初始化完成")
    
    # 初始化薪資資料庫
    init_payroll_db()
    print("✅ 薪資資料庫初始化完成")
    
    print("💰 薪資功能已就緒:")
    print("   📊 自動工時計算")
    print("   💵 薪資結構管理")
    print("   📋 扣款項目計算")
    print("   📱 薪資單生成")
    print("   📈 薪資統計分析")
    print("   🔗 LINE Bot Webhook 已配置")
    
    if FlexMessage:
        print("   ✅ Flex Message 支援已啟用")
    else:
        print("   ⚠️  使用文字版薪資單 (Flex Message 不可用)")
    
    # 啟動應用
    port = int(os.environ.get('PORT', 5011))
    print(f"🌐 薪資系統啟動於 http://localhost:{port}")
    print(f"🔗 Webhook URL: http://localhost:{port}/callback")
    print("💼 準備為企業提供完整薪資解決方案！")
    
    app.run(host='0.0.0.0', port=port, debug=True)