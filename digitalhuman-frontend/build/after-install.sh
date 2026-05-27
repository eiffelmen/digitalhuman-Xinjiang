#!/bin/bash
# Debian包安装后脚本

# 设置应用权限
chmod +x /opt/ZKXH-DigitalHuman/zkxh-digitalhuman

# 创建应用数据目录
mkdir -p /var/lib/zkxh-digitalhuman
chmod 755 /var/lib/zkxh-digitalhuman

# 输出安装成功信息
echo "ZKXH DigitalHuman 安装成功!"
echo "您可以通过以下方式启动应用:"
echo "1. 在应用程序菜单中查找 'ZKXH DigitalHuman'"
echo "2. 在终端运行: zkxh-digitalhuman"
echo "3. 配置为系统服务自启动，请参考部署文档"
