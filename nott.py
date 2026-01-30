import socket
import requests
import asyncio
import stun
import re
import hashlib
import websockets
import json


results = {}

# ================= 基础 IP =================

async def get_lan_ipv4():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        results["lan_ipv4"] = ip
    except Exception as e:
        results["lan_ipv4"] = f"获取失败: {e}"

    print("已获取本地局域网 IPv4 地址...\n")

async def get_public_ipv4():
    try:
        loop = asyncio.get_event_loop()
        ip = await loop.run_in_executor(None, lambda: requests.get("https://4.ipw.cn", timeout=10).text.strip())
        results["public_ipv4"] = ip
    except Exception as e:
        results["public_ipv4"] = None

    print("已获取公网 IPv4 地址...\n")

async def get_public_ipv6():
    try:
        loop = asyncio.get_event_loop()
        ip = await loop.run_in_executor(None, lambda: requests.get("https://6.ipw.cn", timeout=10).text.strip())
        results["public_ipv6"] = ip
    except Exception as e:
        results["public_ipv6"] = None

    print("已获取公网 IPv6 地址...\n")

# ================= NAT 探测 =================

async def stun_probe():
    try:
        loop = asyncio.get_event_loop()
        nat_type, _, _ = await loop.run_in_executor(None, stun.get_ip_info)
        results["nat_type"] = nat_type
    except Exception as e:
        results["nat_type"] = f"探测失败: {e}"

    print("NAT 类型探测完成...\n")

# ================= 外部访问测试 =================

def open_port(ipv6=False):
    if ipv6:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.bind(("::", 0))
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("", 0))
    s.listen(1)
    return s, s.getsockname()[1]

async def tcptest(ip, port, ipv6=False):
    """使用 itdog.cn 的 tcping 服务触发外部连接"""
    try:
        if ipv6:
            url = f"https://www.itdog.cn/tcping_ipv6/[{ip}]:{port}"
        else:
            url = f"https://www.itdog.cn/tcping/{ip}:{port}"
        
        data = {
            "line": "",
            "button_click": "yes",
            "dns_server_type": "isp",
            "dns_server": ""
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.itdog.cn"
        }
        
        # 在线程池中执行阻塞的 HTTP 请求
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: requests.post(url, data=data, headers=headers, timeout=15)
        )
        print(f"POST tcping: {url} (状态码: {response.status_code})")

        match = re.search(r"var task_id='([^']+)'", response.text)
        if not match:
            print("未找到 task_id")
            return
        
        task_id = match.group(1)
        print(f"获取到 task_id: {task_id}")
        
        task_token = hashlib.md5((task_id + "token_20230313000136kwyktxb0tgspm00yo5").encode()).hexdigest()[8:24]
        print(f"生成 task_token: {task_token}")
        
        try:
            async with websockets.connect('wss://www.itdog.cn/websockets',
                user_agent_header = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                origin = "https://www.itdog.cn"
            ) as ws:
                message = json.dumps({
                    "task_id": task_id,
                    "task_token": task_token
                })
                await ws.send(message)
                print(f"WebSocket 已发送任务数据")
                await asyncio.sleep(2)
                
        except Exception as e:
            print(f"WebSocket 连接失败: {e}")
        
    except Exception as e:
        print(f"触发 tcping 时出错: {e}")

async def test_ipv4_access():
    """测试 IPv4 端口的外部可达性"""
    if not results.get("public_ipv4"):
        results["ipv4_accessible"] = "无公网 IPv4"
        return
    
    try:
        server_socket, port = open_port(ipv6=False)
        server_socket.setblocking(False)  # 设置为非阻塞
        
        print(f"\n正在测试 IPv4 可达性: {results['public_ipv4']}:{port}\n")
        print("IPv4 端口等待外部连接...\n")
        
        await asyncio.sleep(2)  # 确保端口完全打开
        
        # 启动触发测试任务
        trigger_task = asyncio.create_task(tcptest(results["public_ipv4"], port, False))
        
        # 等待连接（带超时）
        try:
            loop = asyncio.get_event_loop()
            conn, addr = await asyncio.wait_for(
                loop.sock_accept(server_socket),
                timeout=30.0
            )
            print(f"收到来自 {addr} 的连接")
            conn.close()
            results["ipv4_accessible"] = "可从外部访问 ✓"
        except asyncio.TimeoutError:
            results["ipv4_accessible"] = "无法从外部访问(防火墙/NAT阻止) ✗"
        
        server_socket.close()
        
    except Exception as e:
        results["ipv4_accessible"] = f"测试出错: {str(e)}"

async def test_ipv6_access():
    """测试 IPv6 端口的外部可达性"""
    if not results.get("public_ipv6"):
        results["ipv6_accessible"] = "无公网 IPv6"
        return
    
    try:
        server_socket, port = open_port(ipv6=True)
        server_socket.setblocking(False)
        
        print(f"\n正在测试 IPv6 可达性: [{results['public_ipv6']}]:{port}\n")
        print("IPv6 端口等待外部连接...\n")
        
        await asyncio.sleep(2)
        
        trigger_task = asyncio.create_task(tcptest(results["public_ipv6"], port, True))
        
        try:
            loop = asyncio.get_event_loop()
            conn, addr = await asyncio.wait_for(
                loop.sock_accept(server_socket),
                timeout=30.0
            )
            print(f"收到来自 {addr} 的连接")
            conn.close()
            results["ipv6_accessible"] = "可从外部访问 ✓"
        except asyncio.TimeoutError:
            results["ipv6_accessible"] = "无法从外部访问(防火墙阻止) ✗"
        
        server_socket.close()
        
    except Exception as e:
        results["ipv6_accessible"] = f"测试出错: {str(e)}"

# ================= 主调度 =================

async def main():
    # 第一批：并发获取基础信息
    await asyncio.gather(
        get_lan_ipv4(),
        get_public_ipv4(),
        get_public_ipv6(),
        stun_probe(),
    )
    
    # 第二批：顺序测试外部访问（避免 WebSocket 冲突）
    await test_ipv4_access()
    await test_ipv6_access()
    
    # 输出结果
    print("\n=== 网络探测结果 ===\n")
    for k, v in results.items():
        print(f"{k}: {v}")

    input("\n作者:黎明的曙光\n游戏联机技术交流QQ群:1071321673\n按回车键退出...")

if __name__ == "__main__":
    print("网络联机测试工具已启动\n")
    asyncio.run(main())