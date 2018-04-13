#!/usr/bin/python2

# $Id$


import os
import yaml


class ServerConfig:
	"""
	Helper class for accessing the server configuration parameters.
	"""

	def __init__(self):
		"""
		Constructor that initializes the default configuration file.
		For simplicity, there is only one single config section called [gwn].
		"""

		self.__config = {}
		self.__config_file = '/etc/gwn/server.conf'

		# Read the config if it exists on disk
		if (os.path.isfile(self.__config_file)):
			try:
				with open(self.__config_file, 'r') as cfg:
					cfg_content = cfg.read()
					cfg_raw = yaml.safe_load(cfg_content)
					self.__config = cfg_raw['grains']['gwn']
			except:
				# If the file cannot be read, we'll truncate it
				pass


	def get_all(self):
		"""
		Return the content of the config object as a dictionary.
		"""

		return self.__config



	def set_string(self, key, value):
		"""
		Add or update the given configuration parameter.
		"""
		if value is not None:
			self.__config[key] = value
		elif key in self.__config:
			del(self.__config[key])


	def save(self):
		"""
		Save the current representation of the config object to disk.
		"""
		with open(self.__config_file, 'w') as c:
			shell = { 'grains': { 'gwn': self.__config } }
			yaml.safe_dump(shell, stream=c, default_flow_style=False)



	def get_string(self, option, allowEmpty=False):
		"""
		Retrieve the given config option. If it does not exist, 'None' is returned.
		If 'allowEmpty' is False, an empty string also returns 'None'.
		"""

		if (not self.__config.has_key(option)):
			return None

		value = self.__config[option]
		
		if (allowEmpty or len(value)>1):
			return value
		else:
			return None


