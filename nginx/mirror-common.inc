
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
	log_not_found off;
	autoindex on;
	autoindex_format json;
	include /etc/nginx/conf.d/headers-files.inc;
	add_header Access-Control-Allow-Origin $gz_cors_origin always;
	add_header Vary Origin always;
	add_header Cache-Control "no-cache" always;
	autoindex_localtime off;
	index .no-index;
}

# Directory listings, reached only by the rewrites below; $gz_listing picks one.
# index .no-index keeps a directory holding index.html a listing.
# log_not_found off: a missing directory is the client's 404, not an error to log.
location ^~ /_txt/ {
	internal;
	alias /srv/pub/;
	log_not_found off;
	index .no-index;
	autoindex on;
	autoindex_format xml;
	xslt_stylesheet /etc/nginx/conf.d/listing-txt.xsl;
	include /etc/nginx/conf.d/headers-files.inc;
	include /etc/nginx/conf.d/headers-listing.inc;
}

location ^~ /_html/ {
	internal;
	alias /srv/pub/;
	log_not_found off;
	index .no-index;
	autoindex on;
	autoindex_format html;
	autoindex_exact_size on;
	autoindex_localtime off;
	include /etc/nginx/conf.d/headers-files.inc;
	include /etc/nginx/conf.d/headers-listing.inc;
}

location ^~ /_web/ {
	internal;
	root /srv/mirrors;
	include /etc/nginx/conf.d/headers-site.inc;
	include /etc/nginx/conf.d/headers-listing.inc;
	open_file_cache off;
	try_files $gz_web_page /_app.html =404;
}

location ^~ /distfiles/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	gzip off;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}
}

location ^~ /binpkgs/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}

	location ~ \.gpkg\.tar$ {
		root /srv/pub;
		gzip off;
		access_log /var/log/nginx/mirror.log mirror;
		access_log /var/log/nginx/binpkg.log mirror;
		include /etc/nginx/conf.d/headers-files.inc;
	}

	location ~ ^/binpkgs/x86-64/status\.json$ {
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

location ^~ /unstable/binpkgs/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}

	location ~ \.gpkg\.tar$ {
		root /srv/pub;
		gzip off;
		access_log /var/log/nginx/mirror.log mirror;
		access_log /var/log/nginx/binpkg.log mirror;
		include /etc/nginx/conf.d/headers-files.inc;
	}

	location ~ ^/unstable/binpkgs/x86-64/status\.json$ {
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

location ^~ /gentoo-cjk-kernel/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	gzip off;
	access_log /var/log/nginx/mirror.log mirror;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
	}
}

location ^~ /gentoo-cjk-livecd/ {
	root /srv/pub;
	include /etc/nginx/conf.d/headers-files.inc;

	gzip off;
	access_log /var/log/nginx/mirror.log mirror;

	location ~ /$ {
		rewrite ^ /_$gz_listing$uri last;
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
location = /unstable { return 301 /unstable/; }
location = /unstable/binpkgs { return 301 /unstable/binpkgs/; }
location = /gentoo-cjk-kernel { return 301 /gentoo-cjk-kernel/; }
location = /gentoo-cjk-livecd { return 301 /gentoo-cjk-livecd/; }
location = /files { return 301 /files/; }
# /files/ is a second name for the root directory.
location = /files/ { rewrite ^ /_$gz_listing/ last; }
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

location = /mirror { return 301 /mirrors; }

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
	add_header Access-Control-Allow-Origin $gz_cors_origin always;
	add_header Vary Origin always;
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
}

location ~* \.(css|js)$ {
	add_header Cache-Control "public, max-age=31536000, immutable";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
}

location = / { rewrite ^ /_$gz_listing/ last; }

location ~ /$ { rewrite ^ /_$gz_listing$uri last; }

# Gig-OS images were carried until 2026-10. Old links get a real 404 rather than
# the file browser that answers any other unknown directory.
location ^~ /gigos/ { return 404; }

location / {
	add_header Cache-Control "no-cache";
	include /etc/nginx/conf.d/headers-site.inc;
	open_file_cache off;
	try_files $uri $uri.html $uri/index.html $uri/ =404;
}
