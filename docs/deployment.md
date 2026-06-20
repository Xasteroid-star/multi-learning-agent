# 部署指南

## 方式一：本地开发

### 后端

```bash
cd python
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m api.main
# 访问 http://localhost:8000/docs
```

### 前端

```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:3000
```

## 方式二：Docker Compose（一键部署）

```bash
# 在项目根目录
cp .env.example .env
# 编辑 .env 填入 API Key

docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f python-api

# 停止
docker-compose down
```

服务地址：
- 前端：http://localhost:3000
- Python API：http://localhost:8000/docs
- PostgreSQL：localhost:5432
- Redis：localhost:6379

## 环境要求

| 工具 | 版本 |
|------|------|
| Python | 3.11+ |
| Node.js | 20+ |
| Docker | 24+ |
| Docker Compose | 2.20+ |
