# VCA 手链补货监控：零基础安装教程

本套文件已填好商品链接与判断规则。你不需要安装 Python，也不需要一直开电脑：上传代码后由 GitHub Actions 执行。你需要自己添加 Gmail 应用专用密码和 Bark Key，本套文件没有任何密码。

**先了解结果：**每 10 分钟计划检测一次；ADD TO BAG 按钮可见就发送 Bark 重要警报及邮件；只有 ORDER BY PHONE 可见则安静结束；两个按钮都不可见时任务变红、退出码 1，并保存截图。两个按钮同时可见也按有货处理。有货期间每轮都会提醒，没有去重或冷却，以免漏掉补货。通知只是按钮状态提醒，不保证结账成功。脚本不点击加购、不下单。

**手机说明：**Bark 用设备 Key 找到你的 iPhone，不使用手机号。你提供的 347-859-6258 无需填入代码；`call=1` 是 App 内持续响铃参数，不是拨打电话，也不发短信。Bark 是 iOS App；如果这部手机不是 iPhone，本教程的 Bark 通道不适用。

## 1. 解压并检查文件

1. 下载本次提供的 `luxury-restock.zip`。
2. Mac：在“下载”中双击 ZIP。Windows：右键 ZIP →“全部解压缩”→“提取”。
3. 打开解压出来的 `luxury-restock` 文件夹。
4. 应当看到 `monitor.py`、`requirements.txt`、`test_monitor.py` 和本教程；还有隐藏文件夹 `.github`。Mac 按 Command + Shift + 句号可以显示隐藏文件；Windows 在资源管理器选择“查看”→“显示”→“隐藏的项目”。
5. `.github/workflows/monitor.yml` 是自动运行配置。下面用网页新建它，避免上传时漏掉隐藏目录。

## 2. 在 iPhone 安装 Bark，打开重要警报

1. 打开 iPhone 的 **App Store** → 右下角“搜索”。
2. 搜索 **Bark - Custom Notifications**，核对 App 官方链接：<https://apps.apple.com/app/id1403753865>，下载安装。
3. 打开 Bark。遇到“允许发送通知”→点“允许”；遇到“允许重要警报 / Critical Alerts”→点“允许”。如果没有弹出，进入 App 的设置或重要警报示例，按提示申请权限。
4. 打开手机“设置”→“通知”→“Bark”。有些版本也可从“设置”→“App”→“Bark”→“通知”进入。
5. 打开“允许通知”“声音”“重要警报 / Critical Alerts”。锁定屏幕、通知中心、横幅也建议打开。
6. 返回 Bark，找到自己的推送地址，通常长得像 `https://api.day.app/一串字符/推送内容`。
7. 复制 `api.day.app/` 后面、下一个 `/` 前面的那一串字符。这就是 **BARK_KEY**。不要把整条地址填进去，也不要复制中文“推送内容”。
8. 本代码使用官方 `api.day.app` 服务；自建服务器的 Key 不能直接用于这里。

代码发送 JSON POST，参数为 `level=critical`、`call=1`、`volume=10`、`sound=alarm`。POST 与 URL 的 `?level=critical&call=1` 表达相同参数。Bark 官方说明 critical 可越过静音和勿扰；前提是 iOS 授权成功、手机开机联网且推送可达。不能凭服务器返回成功保证手机一定响铃。后面务必分别在静音、睡眠专注模式下实际测试。若设置里根本没有“重要警报”，先更新 Bark，进入 App 的重要警报示例申请权限，再回到系统设置检查。

## 3. 为 Gmail 创建“应用专用密码”

你可以用 `kathzhangyun@gmail.com` 同时作为发件和收件邮箱，也可以用另一个 Gmail 发件。下文默认发件、收件都是这个地址。

1. 在电脑浏览器打开 <https://myaccount.google.com/>，登录准备作为发件人的 Google 账号。
2. 左侧点“安全性 / Security”（新版可能写“安全性与登录”）。
3. 找到“登录 Google 的方式”→点“两步验证 / 2-Step Verification”。
4. 按页面指示开启两步验证；按需用手机验证。已开启可跳过。
5. 直接打开 <https://myaccount.google.com/apppasswords>，按提示再次登录。
6. 在“应用名称 / App name”输入 `VCA Restock Monitor` →点“创建 / Create”。
7. Google 显示一组 16 位应用专用密码。临时保留这个窗口，稍后粘贴进 GitHub Secret；显示时的空格保留也可以，代码会移除。
8. **不要填普通 Gmail 登录密码**，也不要把应用专用密码写进 `.py`、`.yml`、聊天或公开截图。

找不到入口：确认两步验证已开；工作/学校账户、安全密钥限定设置、Advanced Protection 等可能不支持。需要更换支持应用专用密码的个人 Gmail，不能用普通密码代替。Google 账号密码更改后，旧应用专用密码会失效，需要重新生成并更新 Secret。

## 4. 建立 GitHub 仓库

1. 打开 <https://github.com/>。没有账号点“Sign up”注册，已有账号点“Sign in”登录。
2. 登录后右上角点 **+** → **New repository**（也可直接打开 <https://github.com/new>）。
3. `Repository name` 填 `luxury-restock-monitor`。
4. 选择 **Private**，避免公开个人配置和诊断截图。
5. 勾选 **Add a README file**（新版可能是 README 开关）。
6. 点 **Create repository**。

GitHub 私有仓库的 Actions 会消耗账号额度。每 10 分钟约 144 次/天、4320 次/30 天，每次包含启动和浏览器安装时间；免费额度可能不足。上线前在头像 → Settings → Billing & licensing（或 Billing and plans）查看 Actions 用量、额度与预算。不要把长期运行当成保证免费。配额用尽或预算限制可能使监控停止。

## 5. 上传 Python 文件

1. 在仓库顶部点 **Code**。
2. 点文件列表上方 **Add file** → **Upload files**。
3. 从解压文件夹拖入 `monitor.py`、`requirements.txt`、`test_monitor.py`、`README_零基础教程.md`。不要上传 ZIP，也不要上传任何密码文件。
4. 页面底部 `Commit changes` 区域填写 `Add restock monitor`。
5. 选择直接提交到 `main` → 点 **Commit changes**。
6. 回到 Code 文件列表，确认 `monitor.py` 和 `requirements.txt` 直接出现在顶层，而不是多套了一层 `luxury-restock/`。

## 6. 添加四个 GitHub Secrets

1. 在仓库顶部点 **Settings**。窗口较窄时可能藏在 `…` 菜单里；要用仓库的 Settings，不是头像下的账号设置。
2. 左侧找到 **Secrets and variables** → **Actions**。
3. 确认在 **Secrets** 页签，使用 **Repository secrets**；不要建成 Variables 或 Environment secrets。
4. 点 **New repository secret**。
5. `Name` 输入下表名称，`Secret` 输入对应内容 → 点 **Add secret**。
6. 对四行各重复一次。名称大小写和下划线必须一致。

| Name | Secret 中填写的内容 |
|---|---|
| `GMAIL_USER` | 发件 Gmail，默认填 `kathzhangyun@gmail.com` |
| `GMAIL_APP_PASSWORD` | 第 3 节生成的 16 位应用专用密码 |
| `EMAIL_TO` | `kathzhangyun@gmail.com` |
| `BARK_KEY` | 第 2 节从推送 URL 提取的设备 Key |

保存后看不见原值是正常的。要修改，点对应行铅笔图标 →输入新值 → **Update secret**。不需要配置手机号，不需要额外申请 GitHub Token。工作流只把 Secrets 映射成运行时环境变量，Python 从环境变量读取。

## 7. 新建自动运行文件（路径必须完全一致）

1. 回仓库 **Code** → **Add file** → **Create new file**。
2. 在 `Name your file...` 输入：`.github/workflows/monitor.yml`。输入 `/` 时 GitHub 会自动形成目录。
3. 在电脑上打开解压包中的 `.github/workflows/monitor.yml`，用文本编辑器查看，复制它的**全部内容**。
4. 粘贴到 GitHub 网页的大编辑框中。不要粘贴 Markdown 的 ``` 标记，不要把空格改成 Tab。
5. 点右上方或底部 **Commit changes...** →选择直接提交到 `main` → **Commit changes**。
6. 文件必须在默认分支（本教程是 `main`）；如果创建仓库时默认分支不同，请提交到那个默认分支。
7. 顶部点 **Actions**。如果出现启用确认，点 **I understand my workflows, go ahead and enable them**。
8. 左侧应出现 **VCA Restock Monitor**。没有就回 Code 检查文件是否叫 `monitor.yml`，而不是 `monitor.yml.txt`。

## 8. 先测试邮件

1. 仓库顶部 **Actions** →左侧 **VCA Restock Monitor**。
2. 右侧点 **Run workflow**。
3. `Use workflow from` 选 `main`。
4. `mode` 下拉选 **test-email**。
5. 点弹窗里的绿色 **Run workflow**。
6. 等几秒，刷新页面，点最新一条运行记录 →点 **monitor**，展开 **Test email**。
7. 看到 `Test email accepted by Gmail` 且运行是绿色，代表 Gmail 接受发送。
8. 打开收件邮箱，找标题“【测试】VCA 补货监控邮件”。没看到先查垃圾邮件和“所有邮件”。服务接受不等同于已经进收件箱。

此模式实际执行 `python monitor.py --test-email`，不访问商品页、不发 Bark，也不需要安装 Chromium 浏览器。这样可以单独定位邮件配置问题。

## 9. 测试 Bark 在静音和睡眠模式下响铃

测试会产生较响警报，先选合适时间。

1. 重复上一节 Actions → VCA Restock Monitor → Run workflow。
2. `mode` 选择 **test-bark** →点绿色 **Run workflow**。
3. 等运行结束。手机应收到“【测试】VCA 重要警报”，日志显示 `Test push accepted by Bark`。
4. 将 iPhone 开启静音，再运行一次 **test-bark**，确认能听见。
5. 手机打开控制中心 →长按“专注模式”→选择“睡眠”，再运行一次 **test-bark**，确认能听见。
6. 若收到了但没声音，回到设置 →通知 → Bark，核对“重要警报”和“声音”；确认 App 已更新。关注蓝牙耳机、Apple Watch 等实际通知路由；以你的设备测试结果为准。测试后恢复你原来的专注模式。

网络断开、手机关机、权限关闭时，任何代码都无法保证响铃。GitHub 绿色只说明推送服务接受，不证明 iPhone 已播放声音。`call=1` 的实际持续时间与 iOS/Bark 版本有关，本方案不保证响满 30 秒。

## 10. 开始真实检测

1. 回 Actions → VCA Restock Monitor → Run workflow。
2. `mode` 选 **check** →点绿色 **Run workflow**。
3. 打开运行记录 → **monitor** →展开 **Check stock**。
4. 对照结果：
   - `Stock state: OUT_OF_STOCK`：只有电话订购按钮可见，任务绿色，不发通知。
   - `Stock state: IN_STOCK`：有货按钮可见，本轮分别发送 Bark 和邮件。若一个通道失败，仍会尝试另一个，任务变红。
   - `Monitor failed: ...`：无法可靠判断或发生错误，任务变红，退出码为 1。
5. 脚本等待页面初始加载 8 秒，再轮询可见状态；状态连续稳定 3 秒才接受。对于两个按钮始终不可见的页面，会在等待窗口结束后保存截图。
6. 如果第一个真实检查就有货，手机会响，这是预期行为。
7. 配置文件保存到默认分支后，定时检测自动生效，无需再开一个开关，可以关掉电脑。

默认时间表是 `3,13,23,33,43,53 * * * *`，即每小时第 3、13、23、33、43、53 分钟计划运行，约每 10 分钟一次。GitHub 调度可能延迟甚至丢弃任务，不能保证十分钟内一定通知。它是离散检测，不是持续守着页面，两个检测之间的短暂补货可能漏掉。

## 11. 红色失败时下载截图

1. **Actions** →点红色的运行记录。
2. 点左侧或顶部的 **Summary**，回到本次运行概览。
3. 在页面下方找到 **Artifacts**。
4. 点 `vca-diagnostics-一串数字` 下载 ZIP。
5. 解压，打开 `failure.png`。
6. 如果截图是地区选择、Cookie 弹窗、验证码或拒绝访问页面，说明没有成功读取商品状态；不能把它当作缺货。先用普通浏览器打开商品链接，确认网址及按钮，再查看下一次任务。不要尝试绕过验证码或网站访问限制。
7. 浏览器完全启动失败、安装依赖失败等情况没有可截图的页面，不会有截图；在 **Install Chromium** 或 **Install Python dependency** 步骤看安装日志。截图保留 7 天。

| 常见现象 | 处理方式 |
|---|---|
| `SMTPAuthenticationError` | 重新确认发件邮箱、两步验证、应用专用密码；更改 Google 密码后重新生成 |
| `ValueError` | 检查四个 Repository secrets 名称和值是否缺失；不要往日志里打印密码 |
| Bark 失败 | 确认只填设备 Key，且 Key 属于 `api.day.app`；重装 App 后 Key 可能改变 |
| 截图显示验证页 | 网站可能限制 GitHub 云端 IP；本代码不绕过限制，当前监控无法可靠工作 |
| 日志绿色但手机不响 | 重新做重要警报授权和静音/睡眠测试；绿色不等于设备收到 |
| 定时记录突然不增加 | 检查 Actions 是否被禁用、配额/预算、默认分支和 GitHub 服务状态 |
| `UNKNOWN` 或两个按钮都不见 | 看截图，可能是页面改版、加载失败、地区弹窗；需要修订定位规则 |

## 12. 修改频率、停止与恢复

**修改为约 5 分钟：**Code → `.github` → `workflows` → `monitor.yml` →铅笔图标 →把 cron 改为 `'3-58/5 * * * *'` → Commit changes。GitHub 最短支持 5 分钟，这也会增加执行次数、用量和重复响铃次数。

**修改为约 30 分钟：**同一路径把 cron 改为 `'3,33 * * * *'`，提交。

**暂停：**Actions → VCA Restock Monitor →右上角 `…` → **Disable workflow**。

**恢复：**同一位置点 **Enable workflow**，再手动执行一次 check 确认。

**彻底停用：**先 Disable workflow，再到 Settings → Secrets and variables → Actions 删除四个 Secrets；Google 应用专用密码页删除本项目的密码。不再需要 Bark Key 时可在 App 内按它提供的方法重置。

公开仓库长期无活动时，GitHub 可能自动停用定时任务（官方规则为 60 天无仓库活动）；这里建议用私有仓库，但仍要定期检查 Actions 是否继续运行。GitHub 失败通知也可在个人 Settings → Notifications → Actions 中启用，具体选项依账号界面而异。

## 13. 代码结构和本地验证（可选）

- `monitor.py`：浏览器检测、截图、Gmail SMTP 和 Bark POST。
- `.github/workflows/monitor.yml`：计划任务、手动测试入口、Secrets 映射、失败截图上传。
- `requirements.txt`：固定 Playwright 版本。
- `test_monitor.py`：使用本地 HTML 和模拟通知服务验证关键行为，不会给你发真实通知。

已安装 Python 3.12 的人，可在项目文件夹打开终端运行：

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m unittest -v test_monitor.py
```

不同电脑命令可能叫 `python3`。正式凭据仅配置在 GitHub Secrets；本地测试不需要它们。只有 `ADD TO BAG` 的按钮/链接被 CSS 真正显示时才有货；会检查全部匹配项，兼容隐藏的第一个副本，不以网页源码文字作为库存依据。也额外排除了自身或祖先 `opacity: 0` 的情况。这里“可见”指已渲染、有尺寸且未隐藏，不要求已经滚动到视口内；不要求 enabled。遮罩不会使底层按钮自动判成缺货。代码不会关闭弹窗或替你选择国家。

## 14. 官方参考

- 商品页：<https://www.vancleefarpels.com/us/en/collections/jewelry/alhambra/vcard35600---vintage-alhambra-bracelet-5-motifs.html>。普通网页抓取包含 ADD TO BAG 文本，不能据此证明实时可见或当前有货。
- Playwright 定位器与可见性：<https://playwright.dev/python/docs/api/class-locator#locator-is-visible>
- Bark 官方参数（critical、call）：<https://github.com/Finb/Bark#parameters>
- Bark App：<https://apps.apple.com/app/id1403753865>
- Google 应用专用密码说明：<https://support.google.com/accounts/answer/185833>
- GitHub Secrets：<https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets>
- GitHub 定时任务限制：<https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule>

**交付状态：**代码和教程已经提供。你仍需自己建立仓库、填入 Secrets 并完成两种通知的真实测试；未填凭据前不代表监控已经上线。
