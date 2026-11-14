import asyncio
import json

from agent.product_mode import lan_bind_host


class TCPServer:
    def __init__(self, port, callback, host=None):
        self.port = port
        self.callback = callback
        self.server = None
        self.host = host if host is not None else lan_bind_host()

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port)
        print(f'[TCP] Telemetry Server listening on port {self.port}')
        # We don't await serve_forever here because we want to run in parallel
        # But start_server returns a Server object which starts listening immediately
        asyncio.create_task(self.server.serve_forever())

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"[TCP] New Sensor Connection from {addr}")
        
        try:
            while True:
                # Expect newline delimited JSON
                data = await reader.readline()
                if not data:
                    break
                
                message = data.decode().strip()
                if message:
                   try:
                       json_data = json.loads(message)
                       if self.callback:
                           self.callback(json_data)
                   except json.JSONDecodeError:
                       print(f"[TCP] Invalid JSON received: {message[:50]}...")
                   except Exception as e:
                       print(f"[TCP] Error processing data: {e}")
        except Exception as e:
            print(f"[TCP] Connection Error: {e}")
        finally:
            print(f"[TCP] Connection closed from {addr}")
            writer.close()
            await writer.wait_closed()

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
