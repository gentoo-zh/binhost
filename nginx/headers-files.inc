# distfiles 与二进制包的响应头。
#
# 这些文件的内容和文件名都来自 overlay，任何包都能往里添加，而它们和站点同源。
# 现在恰好没有 .html/.svg 这类会被浏览器执行的 distfile，但那是运气不是策略。
# sandbox 加 default-src 'none' 让这些路径下的内容一律执行不了。
add_header Strict-Transport-Security "max-age=31536000" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header X-Frame-Options "DENY" always;
add_header Content-Security-Policy "default-src 'none'; sandbox" always;
