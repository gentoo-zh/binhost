root /srv/daeuniverse/openwrt;
access_log /var/log/nginx/openwrt-daeuniverse.log mirror;

limit_conn perip 16;
limit_req zone=reqs burst=100 nodelay;

location ^~ /.well-known/acme-challenge/ {
	root /var/www/acme;
}

location / {
	autoindex on;
	autoindex_exact_size on;
	autoindex_localtime off;
	include /etc/nginx/conf.d/headers-files.inc;
}

# apk fetches the index on every update; a new one must show within minutes.
location ~ \.adb$ {
	add_header Cache-Control "public, max-age=300, must-revalidate" always;
	open_file_cache off;
	include /etc/nginx/conf.d/headers-files.inc;
}
