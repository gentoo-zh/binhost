root /srv/daeuniverse/openwrt;
access_log /var/log/nginx/openwrt-daeuniverse.log mirror;

limit_conn perip 16;
limit_req zone=reqs burst=100 nodelay;

location ^~ /.well-known/acme-challenge/ {
	root /var/www/acme;
}

# The feed's CI uploads the guide as /<lang>/index.html and /style.css. Until
# it has, / shows the listing.
location = / {
	if (!-f /srv/daeuniverse/openwrt/en/index.html) {
		rewrite ^ /files/ last;
	}
	add_header Vary "Accept-Language" always;
	add_header Cache-Control "no-cache" always;
	include /etc/nginx/conf.d/headers-files.inc;
	return 302 /$ow_lang/;
}

# The guide pages load only their own scripts, styles, fonts and images.
location ~ ^/(en|zh-cn|zh-tw|assets)/|^/style\.css$ {
	add_header Cache-Control "no-cache" always;
	add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
	add_header X-Content-Type-Options "nosniff" always;
	add_header Referrer-Policy "strict-origin-when-cross-origin" always;
	add_header Content-Security-Policy "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" always;
	add_header Alt-Svc 'h3=":443"; ma=86400' always;
}

# Every file, the guide's directories included; index .no-index keeps a
# directory holding index.html a listing.
location = /files { return 301 /files/; }

location ^~ /files/ {
	alias /srv/daeuniverse/openwrt/;
	index .no-index;
	autoindex on;
	autoindex_exact_size on;
	autoindex_localtime off;
	include /etc/nginx/conf.d/headers-files.inc;
}

location / {
	autoindex on;
	autoindex_exact_size on;
	autoindex_localtime off;
	include /etc/nginx/conf.d/headers-files.inc;
}

# apk fetches the index on every update; a new one must show within minutes.
# Both are binary: mime.types has no .adb, and its .apk is Android's.
location ~ \.adb$ {
	types {}
	default_type application/octet-stream;
	add_header Cache-Control "public, max-age=300, must-revalidate" always;
	open_file_cache off;
	include /etc/nginx/conf.d/headers-files.inc;
}

location ~ \.apk$ {
	types {}
	default_type application/octet-stream;
	include /etc/nginx/conf.d/headers-files.inc;
}
