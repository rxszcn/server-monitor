# -*- coding: utf-8 -*-
"""
Web 管理界面模块 - Flask 轻量仪表盘
提供实时监控数据展示和CSV导出功能
"""

import io
import csv
import os
import logging
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_file

logger = logging.getLogger(__name__)

# 全局引用，由 main.py 在启动时注入
_metrics_store = None
_config_manager = None
_system_monitor = None
_port_monitor = None
_process_monitor = None
_alert_manager = None


def init_web_app(metrics_store, config_manager, system_monitor=None,
                 port_monitor=None, process_monitor=None, alert_manager=None):
    """初始化 Web 应用，注入共享对象"""
    global _metrics_store, _config_manager
    global _system_monitor, _port_monitor, _process_monitor, _alert_manager
    _metrics_store = metrics_store
    _config_manager = config_manager
    _system_monitor = system_monitor
    _port_monitor = port_monitor
    _process_monitor = process_monitor
    _alert_manager = alert_manager


def create_app():
    """创建 Flask 应用实例"""
    # 模板目录在项目根目录下，src/ 的上层
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
    app = Flask(__name__, template_folder=os.path.abspath(template_dir))
    app.config['JSON_AS_ASCII'] = False  # 支持中文输出
    app.config['TEMPLATES_AUTO_RELOAD'] = True  # 模板修改后自动重载
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # 禁用静态文件缓存

    # 所有响应禁用浏览器缓存（开发阶段）
    @app.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # 禁用 Flask 的访问日志（避免干扰监控日志）
    import logging as flask_logging
    flask_logging.getLogger('werkzeug').setLevel(flask_logging.WARNING)

    @app.route('/')
    def index():
        """仪表盘首页"""
        return render_template('dashboard.html')

    @app.route('/api/status')
    def api_status():
        """获取最新监控状态（AJAX 轮询接口）"""
        data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "server_name": _config_manager.get('server.name', 'Unknown'),
            "cpu": {},
            "memory": {},
            "disks": [],
            "ports": [],
            "processes": [],
            "alerts": [],
        }

        # 系统资源数据
        if _system_monitor:
            try:
                data["cpu"] = _system_monitor.get_cpu_info()
                data["memory"] = _system_monitor.get_memory_info()
                data["disks"] = _system_monitor.get_disk_info()
            except Exception as e:
                logger.error(f"获取系统资源数据失败: {e}")

        # 端口状态
        if _port_monitor:
            try:
                port_status = _port_monitor.get_status()
                for port, reachable in port_status.items():
                    data["ports"].append({
                        "address": port,
                        "status": "可连通" if reachable else "不可达",
                        "reachable": reachable,
                    })
            except Exception as e:
                logger.error(f"获取端口状态失败: {e}")

        # 进程状态
        if _process_monitor:
            try:
                proc_status = _process_monitor.get_status()
                for proc, running in proc_status.items():
                    data["processes"].append({
                        "name": proc,
                        "status": "运行中" if running else "未运行",
                        "running": running,
                    })
            except Exception as e:
                logger.error(f"获取进程状态失败: {e}")

        # 告警状态
        if _alert_manager:
            try:
                alert_state = _alert_manager.get_status()
                for key, state in alert_state.items():
                    data["alerts"].append({
                        "key": key,
                        "count": state.get('count', 0),
                        "is_alerting": state.get('is_alerting', False),
                    })
            except Exception as e:
                logger.error(f"获取告警状态失败: {e}")

        # 历史记录数
        if _metrics_store:
            data["stats"] = _metrics_store.get_stats()

        return jsonify({"status": "ok", "data": data})

    @app.route('/api/history')
    def api_history():
        """获取历史指标数据"""
        metric_type = request.args.get('metric', None)
        minutes = int(request.args.get('minutes', 60))
        minutes = min(max(minutes, 1), 1440)  # 限制 1分钟 ~ 24小时

        if _metrics_store:
            records = _metrics_store.get_history(metric_type=metric_type, minutes=minutes)
        else:
            records = []

        return jsonify({"status": "ok", "data": records, "count": len(records)})

    @app.route('/api/export')
    def api_export():
        """导出 CSV 数据"""
        minutes = int(request.args.get('minutes', 60))
        minutes = min(max(minutes, 1), 1440)

        if not _metrics_store:
            return jsonify({"status": "error", "message": "数据存储未初始化"}), 500

        # 生成 CSV 到内存
        records = _metrics_store.get_history(minutes=minutes)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["时间", "类型", "值", "目标"])
        for r in records:
            writer.writerow([r["datetime"], r["type"], r["value"], r["target"]])

        output.seek(0)
        filename = f"monitor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename,
        )

    @app.route('/api/export/file')
    def api_export_file():
        """导出 CSV 到本地文件"""
        minutes = int(request.args.get('minutes', 60))
        minutes = min(max(minutes, 1), 1440)

        if not _metrics_store:
            return jsonify({"status": "error", "message": "数据存储未初始化"}), 500

        filepath = f"logs/monitor_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        success = _metrics_store.export_csv(filepath, minutes=minutes)

        if success:
            return jsonify({"status": "ok", "message": f"已导出到 {filepath}"})
        else:
            return jsonify({"status": "error", "message": "导出失败，请查看日志"}), 500

    @app.route('/api/config')
    def api_config():
        """获取当前配置摘要（隐藏敏感信息）"""
        safe_config = {
            "server_name": _config_manager.get('server.name', ''),
            "system_monitor": {
                "interval": _config_manager.get('system_monitor.interval', 5),
                "cpu_warning": _config_manager.get('system_monitor.cpu.warning_threshold', 80),
                "cpu_critical": _config_manager.get('system_monitor.cpu.critical_threshold', 90),
                "memory_warning": _config_manager.get('system_monitor.memory.warning_threshold', 85),
                "memory_critical": _config_manager.get('system_monitor.memory.critical_threshold', 95),
                "disk_warning": _config_manager.get('system_monitor.disk.warning_threshold', 90),
                "disk_critical": _config_manager.get('system_monitor.disk.critical_threshold', 95),
            },
            "port_monitor": {
                "interval": _config_manager.get('port_monitor.interval', 30),
                "ports": _config_manager.get('port_monitor.ports', []),
            },
            "process_monitor": {
                "interval": _config_manager.get('process_monitor.interval', 30),
                "processes": _config_manager.get('process_monitor.processes', []),
            },
            "alert_silence": _config_manager.get('alert_silence', {}),
        }
        return jsonify({"status": "ok", "data": safe_config})

    return app


def run_web_server(host='0.0.0.0', port=5000):
    """在独立线程中启动 Flask Web 服务器"""
    app = create_app()
    logger.info(f"Web 管理界面已启动: http://{host}:{port}")
    try:
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logger.error(f"Web 服务器异常: {e}")
