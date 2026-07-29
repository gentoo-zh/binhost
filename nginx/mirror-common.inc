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

location = /index.html { return 301 /; }
location ~ ^/(.+)\.html$ { return 301 /$1; }

# /mirror 曾经是一个页面：镜像列表、怎么用镜像、怎么自己开一个。用镜像那部分
# 首页的镜像选择器已经取代，剩下两部分并进了 FAQ。这个地址在 issue 和聊天记录里
# 发出去过，留一条跳转。精确匹配，别把 /mirrors 之类的一起卷走。
location = /mirror { return 301 /faq; }

# 站点资源每次都要回源校验。不发 Cache-Control 时浏览器按启发式规则自己
# 决定缓存多久，改了样式用户看不到。no-cache 不是不缓存，是必须先问一次；
# 内容没变 ETag 会让它只回一个 304。
location ~* \.(css|js|json)$ {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
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
