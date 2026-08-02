# HTTP 和 HTTPS 两个 server 块共用这一份，避免两边改漏一处。
# 由 distfiles.conf 在 server{} 里 include。

root /srv/mirrors;
access_log /var/log/nginx/mirror.log mirror;

limit_conn perip 16;
limit_req zone=reqs burst=100 nodelay;

# nginx 的 add_header 是整块继承的：一个 location 里只要出现任何一条
# add_header，server 层的全部失效。所以下面每个带 add_header 的 location
# 都要把 HSTS 再写一遍，否则站点页面根本收不到这个头。

# Let's Encrypt 的 HTTP-01 验证。续期也走这条，所以必须一直留在 80 上。
location ^~ /.well-known/acme-challenge/ {
	root /var/www/acme;
}

# 目录列表的数据源。页面是静态的，内容从这里取。
# 用 ^~ 而不是普通前缀：下面按正则匹配目录的规则优先级更高，
# 否则 /_ls/foo/ 会被那条规则匹配，返回 HTML 而非 JSON。
# 目录浏览的无脚本回落。/_ls/ 出的是 JSON 给前端用，这里出的是 nginx 自己
# 画的 HTML 列表，文字浏览器和 curl 直接能读。
location ^~ /_raw/ {
	alias /srv/pub/;
	autoindex on;
	autoindex_exact_size off;
	autoindex_localtime on;
	include /etc/nginx/conf.d/headers-site.inc;
}

location ^~ /_ls/ {
	alias /srv/pub/;
	autoindex on;
	autoindex_format json;
	autoindex_localtime off;   # 输出 GMT，前端统一转本地时间
	# 目录里有 index.html 时 nginx 会返回它而不是列表，站点首页正好就在被列的
	# 根目录下。指向一个不会存在的文件名，让 autoindex 始终接管。
	index .no-index;
}

# 被镜像的内容在 /srv/pub，站点自己在 /srv/mirrors。分开放是因为 rsync 模块
# 要暴露前者而不能暴露后者。
#
# 路径不带项目名：这台机器只有 gentoo-zh 一个项目，官方源站也是这样
# （distfiles.gentoo.org/distfiles/，没有 /gentoo/ 那一层）。
# 下游镜像站要加项目名是它们自己的命名空间，不该压到源站头上。

# 用 root 不用 alias：alias 在正则 location 里会把整段 URI 换掉，
# 而 root 是把 URI 追加在后面，正好是我们要的。
location ^~ /distfiles/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	# 目录请求交给前端渲染。外层那条 location ~ /$ 在 ^~ 命中之后不会被考虑，
	# 所以这里要再写一次。
	location ~ /$ {
		root /srv/mirrors;
		add_header Cache-Control "no-cache";
		# 这里回的是 _app.html，是页面不是文件。换成 files 那一份，
		# default-src 'none' 会把它自己的样式和脚本一并挡掉。
		include /etc/nginx/conf.d/headers-site.inc;
		try_files /_app.html =404;
	}
}

# ^~ 命中之后 nginx 不再看正则，所以包体日志和索引缓存都要写在这里面，
# 写成外层的 location ~ 是不会生效的。
location ^~ /binpkgs/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	# 目录请求交给前端渲染。外层那条 location ~ /$ 在 ^~ 命中之后不会被考虑，
	# 所以这里要再写一次。
	location ~ /$ {
		root /srv/mirrors;
		add_header Cache-Control "no-cache";
		# 这里回的是 _app.html，是页面不是文件。换成 files 那一份，
		# default-src 'none' 会把它自己的样式和脚本一并挡掉。
		include /etc/nginx/conf.d/headers-site.inc;
		try_files /_app.html =404;
	}

	# 包体单独记一份日志，方便看哪些包真的有人装
	location ~ \.gpkg\.tar$ {
		root /srv/pub;
		access_log /var/log/nginx/binpkg.log mirror;
		include /etc/nginx/conf.d/headers-files.inc;
	}

	# 首页读它取包数与时间。^~ 命中之后外层那条按扩展名发缓存头的规则不再被
	# 考虑，所以这里要再写一次——不然浏览器按启发式规则自己决定缓存多久，
	# 首页显示的包数可能停在几天前。
	location = /binpkgs/x86-64/status.json {
		root /srv/pub;
		add_header Cache-Control "no-cache";
		include /etc/nginx/conf.d/headers-files.inc;
	}

	# 索引会变。缓存久了用户会拿着旧索引去要新文件，只能拿到 404。
	location ~ /Packages(\.gz)?$ {
		root /srv/pub;
		# 只用 add_header 发这一个头。expires 5m 自己会发一条
		# Cache-Control: max-age=300，两者并用时响应里有两个同名头，取哪个
		# 由中间缓存决定。线上实测确实发了两条。
		add_header Cache-Control "public, max-age=300, must-revalidate";
		include /etc/nginx/conf.d/headers-files.inc;
	}
}

# 昨天发布时用的是带项目名的路径，已经写进过站点。留一段时间的跳转。
location ^~ /gentoo-zh/ {
	rewrite ^/gentoo-zh/(.*)$ /$1 permanent;
}

# 心跳戳，off-box 的检查靠它判断这台机器是不是还在跑 cron。
location = /.health {
	add_header Cache-Control "no-store";
	include /etc/nginx/conf.d/headers-site.inc;
	default_type text/plain;
}

# 浏览根。/binpkgs/ 和 /distfiles/ 各自能浏览，但需要一个能看到全部内容的入口。
#
# 只有根这一层。往下的真实地址是 /binpkgs/、/distfiles/，/files/ 下面没有内容，
# 让它返回页面外壳只会显示一个「路径不存在」，状态码却是 200。
location = /files { return 301 /files/; }
location = /files/ {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	try_files /_app.html =404;
}
location ^~ /files/ { return 404; }

# 浏览页是内部回落目标，不是一个能直接访问的地址
location = /_app { return 404; }

# 页面地址不带扩展名：/faq 而不是 /faq.html。旧地址已经发出去过，统一跳过来。
#
# 必须排在下面那条静态资源规则之前：nginx 取第一个匹配上的正则 location，
# 顺序反了这条永远不会命中。
# 目录浏览页是内部回落目标，不能被下面那条 .html 跳转卷进去——
# try_files 的回落会重新走一遍 location 匹配。精确匹配优先级最高。
location = /_app.html {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
}

# 维护者自己的目录，/~user/ 对应 /home/user/public_html/。
#
# 必须排在下面那两条正则之前，nginx 取第一个匹配上的正则 location。排在后面的
# 话 /~user/ 会被「目录交给前端渲染」那条接走，返回 200 加一段文件浏览器外壳；
# 上传的 .html 会被下一行 301 到一个取不到的地址。只有纯文件碰巧还正常。实测
# 过两种顺序。
#
# disable_symlinks：public_html 里放一个指向 / 的软链接，就等于把这台机器上所有
# 可读文件发出去。site-sync.sh 里防的是同一件事。
#
# 用 files 那组头：上传的 HTML 在本站这个 origin 下跑不了脚本，也不会被索引。
location ~ ^/~([a-z][a-z0-9_-]*)(/.*)?$ {
	alias /home/$1/public_html$2;
	autoindex on;
	disable_symlinks if_not_owner from=/home;
	include /etc/nginx/conf.d/headers-files.inc;
}

location = /index.html { return 301 /; }
location ~ ^/(.+)\.html$ { return 301 /$1; }

# /mirror 曾经是一个页面：镜像列表、怎么用镜像、怎么自己开一个。用镜像那部分
# 首页的镜像选择器已经取代，剩下两部分并进了 FAQ。这个地址在 issue 和聊天记录里
# 发出去过，留一条跳转。精确匹配，别把 /mirrors 之类的一起卷走。
location = /mirror { return 301 /faq; }

# 站点图标只有 webp 一份。页面里都写了 link rel=icon，但书签、抓取器这些场合
# 浏览器会直接要 /favicon.ico，不接就是每次访问多一条 404。
location = /favicon.ico { return 301 /assets/logo.webp; }

# 站点资源每次都要回源校验。不发 Cache-Control 时浏览器按启发式规则自己
# 决定缓存多久，改了样式用户看不到。no-cache 不是不缓存，是必须先问一次；
# 内容没变 ETag 会让它只回一个 304。
location = /robots.txt {
	root /srv/mirrors;
	include /etc/nginx/conf.d/headers-site.inc;
}

# 包列表的纯文本一份。表格是脚本画的，文字浏览器只看得到「加载中」。
location = /packages.txt {
	root /srv/mirrors;
	default_type text/plain;
	charset utf-8;
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
}

# json 是数据，每次都要验；css 与 js 的引用带内容指纹（见 render-chrome.py），
# 改了文件 URL 就变，所以可以放心长缓存，省掉每次访问的那轮回源验证。
location ~* \.json$ {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
}

location ~* \.(css|js)$ {
	add_header Cache-Control "public, max-age=31536000, immutable";
	include /etc/nginx/conf.d/headers-site.inc;
	# open_file_cache 缓存的是文件描述子，同步换掉文件之后它还指着旧的那份。
	# 对镜像树无所谓，对这里是错的：那两分钟里，新的页面引用新的指纹，取到的
	# 却是旧的内容，还带一年的 immutable，于是旧内容按新指纹在浏览器里存一年。
	# 站点资源只有几个文件，关掉这一项没有代价。
	open_file_cache off;
}

# 只有以斜杠结尾的请求才是「浏览目录」，交给前端渲染。
#
# 这条界限很重要：早先是所有找不到的路径都回落到 _app.html，于是一个不存在的
# 包会返回 200 加一段 HTML。portage 拿到的不是 404 而是一个「下载成功」的
# 网页，出错的地方离真正的原因会隔得非常远。
location ~ /$ {
	add_header Cache-Control "no-cache";   # 同上，目录和首页也走 index.html
	include /etc/nginx/conf.d/headers-site.inc;
	try_files ${uri}index.html /_app.html;
}

error_page 404 /404.html;
location = /404.html {
	internal;
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
}

# 文件按原样给，给不出就 404。
# $uri/ 那一档是为了让不带结尾斜杠的目录请求内部跳到上面那条去。
location / {
	# 页面走 $uri.html 这一档进来，上面按后缀匹配的规则不会再作用于它们，
	# 所以缓存头写在这里。
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	try_files $uri $uri.html $uri/index.html $uri/ =404;
}
