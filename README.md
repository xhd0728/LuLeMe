# 撸了么 (Luleme)

一个赛博朋克风的自嗨打卡 + 恶趣味成就 + 60 秒好友对战小网页。  
前端纯 HTML/CSS/JS，后端 Flask + SQLite，开箱即用。

## 功能亮点
- 登录/注册，多用户独立数据
- 今日/本月/总次数统计 + 日历标记
- 恶趣味成就体系，解锁时会弹窗提示
- 成就/排行榜侧边栏，可一键收起；移动端友好
- 交互改成“香蕉上下撸动”手势
- 60 秒好友对战小游戏（只计局内次数，不入打卡）
- 清除今日记录按钮
- 数据本地 SQLite，单机即可玩

## 快速开始
```bash
cd /local_data/meisen/project/Luleme
pip install -r requirements.txt
python app.py
# 打开 http://localhost:5000
```

## 玩法说明
### 日常打卡
1. 登录/注册
2. 对着香蕉上下滑动一下（>50px）即记录一次
3. 成就解锁会右上角弹窗
4. 今日记录可一键清除

### 60 秒联机对战（不影响打卡）
1. 登录后点击「创建房间」得到房间码，分享给好友
2. 好友输入房间码点击加入
3. 房主点「开始对战」后倒计时 60 秒
4. 对战中继续撸香蕉即累计本局次数；榜单实时刷新

## 目录结构
- `app.py`：Flask API（登录/记录/成就/排行榜/对战）
- `index.html`：前端页面与交互
- `requirements.txt`：后端依赖
- `luleme.db`：SQLite 数据文件（运行后生成）

## API 简述
- `POST /api/register` / `POST /api/login` / `POST /api/logout`
- `GET /api/me`：用户概要 + 当月记录
- `POST /api/record`：日常记录 +1
- `DELETE /api/record/today`：清除今日记录
- `GET /api/leaderboard`：总榜 & 月榜
- 对战：
  - `POST /api/battle/create` / `POST /api/battle/join`
  - `POST /api/battle/start`
  - `POST /api/battle/tap`
  - `GET /api/battle/state?code=xxxxxx`

## 适配说明
- 小屏幕：侧边栏可折叠（<720px 默认折叠），香蕉区域缩小
- PC：侧边栏默认展开，便于查看成就与排行榜

## 注意
- 对战模式计数不入日历打卡
- 房间数据在内存中，结束后自动清理（约 5 分钟）

## License
MIT
