# 站点页面与资源的响应头。
#
# nginx 的 add_header 是整块继承的：一个 location 里只要出现任何一条 add_header，
# 上层的全部失效。所以每个用到 add_header 的 location 都要 include 这一份，
# 而不是指望继承。手抄十五遍 HSTS 就是这么来的。
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
# 文件名和内容都来自 overlay，不是我们能约束的。禁止浏览器按内容猜类型。
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header X-Frame-Options "DENY" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), interest-cohort=()" always;
# 页面里有内联脚本，所以 script-src 只能留 unsafe-inline；能挡住的是外部脚本、
# 内联事件处理器之外的注入面，以及被别人嵌进 iframe。
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" always;
add_header Alt-Svc 'h3=":443"; ma=86400' always;
