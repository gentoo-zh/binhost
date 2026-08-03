
root /srv/mirrors;
access_log /var/log/nginx/mirror.log mirror;

limit_conn perip 16;
limit_req zone=reqs burst=100 nodelay;


location ^~ /.well-known/acme-challenge/ {
	root /var/www/acme;
}

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
	include /etc/nginx/conf.d/headers-files.inc;
	autoindex_localtime off;
	index .no-index;
}


location ^~ /distfiles/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	gzip off;

	location ~ /$ {
		root /srv/mirrors;
		add_header Cache-Control "no-cache";
		include /etc/nginx/conf.d/headers-site.inc;
		try_files /_app.html =404;
	}
}

location ^~ /binpkgs/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	location ~ /$ {
		root /srv/mirrors;
		add_header Cache-Control "no-cache";
		include /etc/nginx/conf.d/headers-site.inc;
		try_files /_app.html =404;
	}

	location ~ \.gpkg\.tar$ {
		root /srv/pub;
		gzip off;
		access_log /var/log/nginx/mirror.log mirror;
		access_log /var/log/nginx/binpkg.log mirror;
		include /etc/nginx/conf.d/headers-files.inc;
	}

	location = /binpkgs/x86-64/status.json {
		root /srv/pub;
		add_header Cache-Control "no-cache";
		include /etc/nginx/conf.d/headers-files.inc;
		open_file_cache off;
	}

	location ~ /Packages(\.gz)?$ {
		root /srv/pub;
		add_header Cache-Control "public, max-age=300, must-revalidate";
		include /etc/nginx/conf.d/headers-files.inc;
		open_file_cache off;
	}
}

location ^~ /gentoo-zh/ {
	rewrite ^/gentoo-zh/(.*)$ /$1 permanent;
}

location = /.health {
	add_header Cache-Control "no-store";
	include /etc/nginx/conf.d/headers-site.inc;
	default_type text/plain;
}

location = /distfiles { return 301 /distfiles/; }
location = /binpkgs { return 301 /binpkgs/; }
location = /files { return 301 /files/; }
location = /files/ {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	try_files /_app.html =404;
}
location ^~ /files/ { return 404; }

location = /_app { return 404; }

location = /_app.html {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
}

location ~ ^/~([a-z][a-z0-9_-]*)(/.*)?$ {
	alias /home/$1/public_html$2;
	autoindex on;
	disable_symlinks if_not_owner from=/home;
	include /etc/nginx/conf.d/headers-files.inc;
}

location = /index.html { return 301 /; }
location ~ ^/(.+)\.html$ { return 301 /$1; }

location = /mirror { return 301 /faq; }

location = /favicon.ico { return 301 /assets/logo.webp; }

location = /robots.txt {
	root /srv/mirrors;
	include /etc/nginx/conf.d/headers-site.inc;
}

location = /packages.txt {
	root /srv/mirrors;
	default_type text/plain;
	charset utf-8;
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
}

location ~* \.json$ {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
}

location ~* \.(css|js)$ {
	add_header Cache-Control "public, max-age=31536000, immutable";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
}

location ~ /$ {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
	try_files ${uri}index.html /_app.html;
}

error_page 404 /404.html;
location = /404.html {
	internal;
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
}

location / {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
	try_files $uri $uri.html $uri/index.html $uri/ =404;
}
