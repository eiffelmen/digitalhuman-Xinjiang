#!/bin/bash

# ZKXH Digital Human 系统服务安装脚本
# 用于在Ubuntu系统中配置开机自启动

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 服务名称
SERVICE_NAME="zkxh-digitalhuman"
SERVICE_FILE="${SERVICE_NAME}.service"

# 检查是否以root权限运行
check_root() {
    if [ "$EUID" -ne 0 ]; then 
        echo -e "${RED}错误: 请使用root权限运行此脚本${NC}"
        echo "使用方法: sudo $0"
        exit 1
    fi
}

# 检查应用是否已安装
check_app_installed() {
    if [ ! -f "/opt/ZKXH-DigitalHuman/zkxh-digitalhuman" ]; then
        echo -e "${RED}错误: 应用未安装${NC}"
        echo "请先安装ZKXH Digital Human应用"
        exit 1
    fi
}

# 复制服务文件
install_service() {
    echo -e "${YELLOW}正在安装systemd服务...${NC}"
    
    # 查找服务文件
    if [ -f "./${SERVICE_FILE}" ]; then
        SERVICE_SOURCE="./${SERVICE_FILE}"
    elif [ -f "../build/${SERVICE_FILE}" ]; then
        SERVICE_SOURCE="../build/${SERVICE_FILE}"
    else
        echo -e "${RED}错误: 找不到服务文件 ${SERVICE_FILE}${NC}"
        exit 1
    fi
    
    # 复制服务文件到systemd目录
    cp "${SERVICE_SOURCE}" "/etc/systemd/system/${SERVICE_FILE}"
    chmod 644 "/etc/systemd/system/${SERVICE_FILE}"
    
    echo -e "${GREEN}服务文件安装成功${NC}"
}

# 配置服务
configure_service() {
    echo -e "${YELLOW}正在配置服务...${NC}"
    
    # 重新加载systemd配置
    systemctl daemon-reload
    
    # 启用服务（开机自启动）
    systemctl enable ${SERVICE_NAME}
    
    echo -e "${GREEN}服务配置成功${NC}"
}

# 启动服务
start_service() {
    echo -e "${YELLOW}正在启动服务...${NC}"
    
    systemctl start ${SERVICE_NAME}
    
    # 等待2秒后检查状态
    sleep 2
    
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        echo -e "${GREEN}服务启动成功！${NC}"
    else
        echo -e "${RED}服务启动失败，请检查日志${NC}"
        echo "查看日志命令: sudo journalctl -u ${SERVICE_NAME} -f"
        exit 1
    fi
}

# 显示服务状态
show_status() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}服务状态:${NC}"
    systemctl status ${SERVICE_NAME} --no-pager
    echo -e "${GREEN}========================================${NC}"
    echo ""
}

# 显示使用说明
show_usage() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}服务管理命令:${NC}"
    echo -e "${YELLOW}启动服务:${NC}   sudo systemctl start ${SERVICE_NAME}"
    echo -e "${YELLOW}停止服务:${NC}   sudo systemctl stop ${SERVICE_NAME}"
    echo -e "${YELLOW}重启服务:${NC}   sudo systemctl restart ${SERVICE_NAME}"
    echo -e "${YELLOW}查看状态:${NC}   sudo systemctl status ${SERVICE_NAME}"
    echo -e "${YELLOW}查看日志:${NC}   sudo journalctl -u ${SERVICE_NAME} -f"
    echo -e "${YELLOW}禁用自启:${NC}   sudo systemctl disable ${SERVICE_NAME}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
}

# 卸载服务
uninstall_service() {
    echo -e "${YELLOW}正在卸载服务...${NC}"
    
    # 停止服务
    systemctl stop ${SERVICE_NAME} 2>/dev/null || true
    
    # 禁用服务
    systemctl disable ${SERVICE_NAME} 2>/dev/null || true
    
    # 删除服务文件
    rm -f "/etc/systemd/system/${SERVICE_FILE}"
    
    # 重新加载systemd
    systemctl daemon-reload
    
    echo -e "${GREEN}服务卸载成功${NC}"
}

# 主函数
main() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}ZKXH Digital Human 服务安装程序${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    
    # 解析命令行参数
    case "${1:-install}" in
        install)
            check_root
            check_app_installed
            install_service
            configure_service
            start_service
            show_status
            show_usage
            ;;
        uninstall)
            check_root
            uninstall_service
            ;;
        restart)
            check_root
            systemctl restart ${SERVICE_NAME}
            show_status
            ;;
        status)
            systemctl status ${SERVICE_NAME} --no-pager
            ;;
        *)
            echo "使用方法: $0 {install|uninstall|restart|status}"
            echo ""
            echo "  install   - 安装并启动服务"
            echo "  uninstall - 卸载服务"
            echo "  restart   - 重启服务"
            echo "  status    - 查看服务状态"
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
