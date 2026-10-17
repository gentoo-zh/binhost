<?xml version="1.0" encoding="utf-8"?>
<!-- Plain-text directory listing for curl and scripts, one entry per line:
     <mtime, ISO 8601 UTC>  <bytes, or - for a directory>  <name, / after a directory>
     The name comes last so a name with spaces survives awk and cut. -->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="text" media-type="text/plain" encoding="utf-8"/>
  <xsl:template match="/">
    <xsl:for-each select="list/directory | list/file">
      <xsl:value-of select="@mtime"/>
      <xsl:text>  </xsl:text>
      <xsl:choose>
        <xsl:when test="self::file"><xsl:value-of select="@size"/></xsl:when>
        <xsl:otherwise><xsl:text>-</xsl:text></xsl:otherwise>
      </xsl:choose>
      <xsl:text>  </xsl:text>
      <xsl:value-of select="."/>
      <xsl:if test="self::directory"><xsl:text>/</xsl:text></xsl:if>
      <xsl:text>&#10;</xsl:text>
    </xsl:for-each>
    <!-- nginx answers an empty result with 500, so an empty directory gets one newline. -->
    <xsl:if test="not(list/*)"><xsl:text>&#10;</xsl:text></xsl:if>
  </xsl:template>
</xsl:stylesheet>
