import csv
import gc
import os
from os import listdir
from os.path import isfile, join
import re
import ConfigParser
import sys
from collections import defaultdict
from xrenner_rule import CorefRule

"""
LexData class - container object for lexical information, gazetteers etc.

Author: Amir Zeldes
"""

class LexData:
	"""
	Class to hold lexical information from gazetteers and training data.
	Use model argument to define subdirectory under models/ for reading different sets of
	configuration files.
	"""
	def __init__(self, model,override=None):
		"""
		:param model: model - string name of the model to read from models/
		:param override: override - optional name of a section to use in models/override.ini
		"""
		gc.disable()
		self.model = model
		self.atoms = {}
		self.mod_atoms = {}

		model_path = os.path.dirname(os.path.realpath(__file__)) + os.sep + ".." + os.sep + "models" + os.sep + model + os.sep
		model_files = [f for f in listdir(model_path) if isfile(join(model_path, f))]

		# Mandatory files must be included in model directory
		self.coref_rules = self.parse_coref_rules(self.read_delim('coref_rules.tab', 'single'))
		self.entities = self.read_delim('entities.tab', 'triple')
		self.entity_heads = self.read_delim('entity_heads.tab', 'triple')
		self.pronouns= self.read_delim('pronouns.tab', 'double')
		# Get configuration
		self.filters = self.get_filters(override)

		# Optional files improve model accuracy
		self.names = self.read_delim('names.tab') if "names.tab" in model_files else {}
		self.stop_list = self.read_delim('stop_list.tab', 'low') if "stop_list.tab" in model_files else set([])
		self.open_close_punct = self.read_delim('open_close_punct.tab') if "open_close_punct.tab" in model_files else {}
		self.open_close_punct_rev = dict((v, k) for k, v in self.open_close_punct.items())
		self.entity_mods = self.read_delim('entity_mods.tab', 'triple', 'mod_atoms') if "entity_mods.tab" in model_path else {}
		self.entity_deps = self.read_delim('entity_deps.tab','quadruple') if "entity_deps.tab" in model_files else {}
		self.hasa = self.read_delim('hasa.tab', 'triple_numeric') if "hasa.tab" in model_files else {}
		self.coref = self.read_delim('coref.tab') if "coref.tab" in model_files else {}
		self.numbers=self.read_delim('numbers.tab','double') if "numbers.tab" in model_files else {}
		self.affix_tokens = self.read_delim('affix_tokens.tab') if "affix_tokens.tab" in model_files else {}
		self.antonyms = self.read_antonyms() if "antonyms.tab" in model_files else {}
		self.isa = self.read_isa() if "isa.tab" in model_files else {}
		self.debug = self.read_delim('debug.tab') if "debug.tab" in model_files else {"ana":"","ante":"","ablations":""}

		# Compile atom and first + last name data
		self.atoms = self.get_atoms()
		self.first_names, self.last_names = self.get_first_last_names(self.names)

		self.pos_agree_mappings = self.get_pos_agree_mappings()
		self.last = {}

		self.morph = self.get_morph()
		self.func_substitutes_forward, self.func_substitutes_backward = self.get_func_substitutes()

		gc.enable()

	def read_delim(self, filename, mode="normal", atom_list_name="atoms"):
		"""
		Generic file reader for lexical data in model directory

		:param filename: string - name of the file
		:param mode: single, double, triple, quadruple, triple_numeric or low reading mode
		:param atom_list_name: list of atoms to use for triple reader mode
		:return: compiled lexical data, usually a structured dictionary or set depending on number of columns
		"""
		if atom_list_name == "atoms":
			atom_list = self.atoms
		elif atom_list_name == "mod_atoms":
			atom_list = self.mod_atoms
		with open(os.path.dirname(os.path.realpath(__file__)) + os.sep + ".." + os.sep + "models" + os.sep + self.model + os.sep + filename, 'rb') as csvfile:
			reader = csv.reader(csvfile, delimiter='\t', escapechar="\\")
			if mode == "low":
				return set([rows[0].lower() for rows in reader if not rows[0].startswith('#') and not len(rows[0]) == 0])
			elif mode == "single":
				return list((rows[0]) for rows in reader if not rows[0].startswith('#') and not len(rows[0].strip()) == 0)
			elif mode == "double":
				out_dict = {}
				for rows in reader:
					if not rows[0].startswith('#') and not len(rows[0]) == 0:
						if rows[0] in out_dict:
							out_dict[rows[0]].append(rows[1])
						else:
							out_dict[rows[0]] = [rows[1]]
				return out_dict
			elif mode == "triple":
				out_dict = {}
				for rows in reader:
					if not rows[0].startswith('#'):
						if rows[2].endswith('@'):
							rows[2] = rows[2][0:-1]
							atom_list[rows[0]] = rows[1]
						if rows[0] in out_dict:
							out_dict[rows[0]].append(rows[1] + "\t" + rows[2])
						else:
							out_dict[rows[0]] = [rows[1] + "\t" + rows[2]]
				return out_dict
			elif mode == "triple_numeric":
				out_dict = defaultdict(lambda: defaultdict(int))
				for row in reader:
					if not row[0].startswith("#"):
						out_dict[row[0]][row[1]] = int(row[2])
				return out_dict
			elif mode == "quadruple":
				out_dict = defaultdict(lambda: defaultdict(lambda: defaultdict(str)))
				for row in reader:
					if not row[0].startswith("#"):
						out_dict[row[0]][row[1]][row[2]] = int(row[3])
				return out_dict
			else:
				return dict((rows[0], rows[1]) for rows in reader if not rows[0].startswith('#'))

	def get_atoms(self):
		"""
		Function to compile atom list for atomic markable recognition. Currently treats listed persons, places,
		organizations and inanimate objects from lexical data as atomic by default.

		:return: dictionary of atoms.
		"""
		atoms = self.atoms
		places = dict((key, value[0]) for key, value in self.entities.items() if value[0].startswith(self.filters["place_def_entity"]+"\t"))
		atoms.update(places)
		atoms.update(self.names)
		persons = dict((key, value[0]) for key, value in self.entities.items() if value[0].startswith(self.filters["person_def_entity"]+"\t"))
		atoms.update(persons)
		organizations = dict((key, value[0]) for key, value in self.entities.items() if value[0].startswith(self.filters["organization_def_entity"]+"\t"))
		atoms.update(organizations)
		objects = dict((key, value[0]) for key, value in self.entities.items() if value[0].startswith(self.filters["object_def_entity"]+"\t"))
		atoms.update(objects)
		return atoms

	@staticmethod
	def get_first_last_names(names):
		"""
		Collects separate first and last name data from the collection in names.tab

		:param names: The complete names dictionary from names.tab, mapping full name to agreement
		:return: [firsts, lasts] - list containing dictionary of first names to agreement and set of last names
		"""
		firsts = {}
		lasts = set([])
		for name in names:
			if " " in name:
				parts = name.split(" ")
				firsts[parts[0]] = names[name]  # Get heuristic gender for this first name
				lasts.update(parts[len(parts)-1])  # Last name is a set, no gender info
		return [firsts,lasts]

	def read_antonyms(self):
		"""
		Function to created dictionary from each word to all its antonyms in antonyms.tab

		:return: dictionary from words to antonym sets
		"""
		set_list = self.read_delim('antonyms.tab', 'low')
		output = defaultdict(set)
		for antoset in set_list:
			members = antoset.lower().split(",")
			for member in members:
				output[member].update(members)
				output[member].remove(member)
		return output

	def read_isa(self):
		"""
		Reads isa.tab into a dictionary from words to lists of isa-matches

		:return: dictionary from words to lists of corresponding isa-matches
		"""
		isa_list = self.read_delim('isa.tab')
		output = {}
		for isa in isa_list:
			output[isa] = []
			members = isa_list[isa].split(",")
			for member in members:
				output[isa].append(member.lower())
		return output

	def get_filters(self, override=None):
		"""
		Reads model settings from config.ini and possibly overrides from override.ini

		:param override: optional section name in override.ini
		:return: filters - dictionary of settings from config.ini with possible overrides
		"""

		#e.g., override = 'OntoNotes'
		config = ConfigParser.ConfigParser()
		config.read(os.path.dirname(os.path.realpath(__file__)) + os.sep + ".." + os.sep + "models" + os.sep + self.model + os.sep + 'config.ini')
		filters = {}
		options = config.options("main")

		if override:
			config_ovrd = ConfigParser.ConfigParser()
			config_ovrd.read(os.path.dirname(os.path.realpath(__file__)) + os.sep + ".." + os.sep + "models" + os.sep + self.model + os.sep + 'override.ini')
			try:
				options_ovrd = config_ovrd.options(override)
			except ConfigParser.NoSectionError:
				sys.stderr.write("\nNo section " +  override + " in override.ini in model " + self.model + "\n")
				sys.exit()

		for option in options:
			if override and option in options_ovrd:
				try:
					option_string = config_ovrd.get(override, option)
					if option_string == -1:
						pass
					else:
						if option_string.startswith("/") and option_string.endswith("/"):
							option_string = option_string[1:-1]
							filters[option] = re.compile(option_string)
						elif option_string == "True" or option_string == "False":
							filters[option] = config_ovrd.getboolean(override, option)
						elif option_string.isdigit():
							filters[option] = config_ovrd.getint(override, option)
						else:
							filters[option] = option_string
				except:
					print("exception on %s!" % option)
					filters[option] = None
				continue
			try:
				option_string = config.get("main", option)
				if option_string == -1:
					pass
				else:
					if option_string.startswith("/") and option_string.endswith("/"):
						option_string = option_string[1:-1]
						filters[option] = re.compile(option_string)
					elif option_string == "True" or option_string == "False":
						filters[option] = config.getboolean("main", option)
					elif option_string.isdigit():
						filters[option] = config.getint("main", option)
					else:
						filters[option] = option_string
			except:
				print("exception on %s!" % option)
				filters[option] = None

		return filters

	def lemmatize(self, token):
		"""
		Simple lemmatization function using rules from lemma_rules in config.ini

		:param token: ParsedToken object to be lemmatized
		:return: string - the lemma
		"""

		lemma_rules = self.filters["lemma_rules"]
		lemma = token.text
		for rule in lemma_rules.split(";"):
			rule_part = rule.split("/")
			pos_pattern = re.compile(rule_part[0])
			if pos_pattern.search(token.pos):
				lemma_pattern = re.compile(rule_part[1])
				lemma = lemma_pattern.sub(rule_part[2], lemma)
		if self.filters["auto_lower_lemma"] == "all":
			return lemma.lower()
		elif self.filters["auto_lower_lemma"] == "except_all_caps":
			if lemma.upper() == lemma:
				return lemma
			else:
				return lemma.lower()
		else:
			return lemma

	def get_func_substitutes(self):
		"""
		Function for semi-hard-wired function substitutions based on function label and dependency direction.
		Uses func_substitute_forward and func_substitute_backward settings in config.ini

		:return: list of compiled substitutions_forward, substitutions_backward
		"""

		substitutions_forward = {}
		substitutions_backward = {}
		subst_rules = self.filters["func_substitute_forward"]
		for rule in subst_rules.split(";"):
			rule_part = rule.split("/")
			substitutions_forward[rule_part[0]] = [rule_part[1],rule_part[2]]
		subst_rules = self.filters["func_substitute_backward"]
		for rule in subst_rules.split(";"):
			rule_part = rule.split("/")
			substitutions_backward[rule_part[0]] = [rule_part[1],rule_part[2]]
		return [substitutions_forward,substitutions_backward]

	def process_morph(self, token):
		"""
		Simple mechanism for substituting values in morph feature of input tokens. For more elaborate sub-graph
		dependent manipultations, use depedit module

		:param token: ParsedToken object to edit morph feature
		:return: string - the edited morph feature
		"""

		morph_rules = self.filters["morph_rules"]
		morph = token.morph
		for rule in morph_rules.split(";"):
			rule_part = rule.split("/")
			morph = re.sub(rule_part[0], rule_part[1], morph)
		return morph

	def get_pos_agree_mappings(self):
		"""
		Gets dictionary mapping POS categories to default agreement classes, e.g. NNS > plural

		:return: mapping dictionary
		"""

		mappings = {}
		rules = self.filters["pos_agree_mapping"]
		for rule in rules.split(";"):
			if ">" in rule:
				mappings[rule.split(">")[0]] = rule.split(">")[1]

		return mappings

	@staticmethod
	def parse_coref_rules(rule_list):
		"""
		Reader function to pass coref_rules.tab into CorefRule objects

		:param rule_list: textual list of rules
		:return: list of compiled CorefRule objects
		"""

		output=[]
		for rule in rule_list:
			output.append(CorefRule(rule))

		return output

	def get_morph(self):
		"""
		Compiles morphlogical affix dictionary based on members of entity_heads.tab

		:return: dictionary from affixes to dictionaries mapping classes to type frequencies
		"""
		morph = {}
		for head in self.entity_heads:
			for i in range(1, self.filters["max_suffix_length"]):
				if len(head) > i:
					substring = head[len(head)-i:]
					entity_list = self.entity_heads[head]
					if substring in morph:
						for entity in entity_list:
							entity_class = entity.split("\t")[0]
							if entity_class in morph[substring]:
								morph[substring][entity_class] += 1
							else:
								morph[substring][entity_class] = 1
					else:
						for entity in entity_list:
							entity_class = entity.split("\t")[0]
							morph[substring] = {entity_class:1}
		return morph
