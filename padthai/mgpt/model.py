# -*- coding: utf-8 -*-
import os
import torch
from typing import List
import logging
from torch.utils.data import random_split
from ..dataset import ListDataset
from transformers import (
    GPT2Tokenizer,
    TrainingArguments,
    Trainer,
    GPT2LMHeadModel
)
torch.manual_seed(42)


class mGPTFewShot:
    """
    Few-Shot Learning using mGPT

    Default model: https://huggingface.co/sberbank-ai/mGPT
    Original code from https://link.medium.com/4FfbALWz8gb
    """
    def __init__(
        self,
        model_dir: str,
        device: str = torch.device("cuda" if torch.cuda.is_available() else "cpu").type,
        pretrained: str = "sberbank-ai/mGPT"
    ):
        """
        :param str model_dir: path of model directory
        :param str device: device
        :param str device: device (cuda is default)
        """
        self.device = device
        self.model_dir = model_dir
        self.pretrained = pretrained
        if not os.path.exists(self.model_dir):
            self._init_model()
        else:
            self.load_model()

    def _init_model(self) -> None:
        """
        initialize GPT-2 model
        """
        self.tokenizer = GPT2Tokenizer.from_pretrained(
            self.pretrained
        )
        self.tokenizer.add_special_tokens({'pad_token': '[PAD]'})
        self.bos_token = self.tokenizer.bos_token
        self.eos_token = self.tokenizer.eos_token
        self.pad_token = self.tokenizer.pad_token
        self.tokenizer.save_pretrained(self.model_dir)
        self.model = GPT2LMHeadModel.from_pretrained(
            self.pretrained
        ).to(self.device)
        self.model.resize_token_embeddings(len(self.tokenizer))

    def load_model(self):
        """
        Load model from path of model directory
        """
        self.model_dir = self.model_dir
        self.tokenizer = GPT2Tokenizer.from_pretrained(
            self.model_dir
        )
        self.bos_token = self.tokenizer.bos_token
        self.eos_token = self.tokenizer.eos_token
        self.pad_token = self.tokenizer.pad_token
        self.model = GPT2LMHeadModel.from_pretrained(
            self.model_dir
        ).to(self.device)
        self.model.resize_token_embeddings(len(self.tokenizer))

    def train(
        self,
        train_data: List[str],
        logging_dir: str,
        test_data: List[str] = None,
        num_train_epochs: int = 10,
        train_size: float = 0.95,
        batch_size: int = 2,
        save_every_epochs: bool = True,
        max_length: int = None
    ):
        """
        Train model

        :param List[str] train_data: List text for training
        :param str logging_dir: logging directory
        :param List[str] test_data: List text for testing (default is None)
        :param int num_train_epochs: Number train epochs (default is 10)
        :param float train_size: size of train set (if test_data is None) (default is 0.95)
        :param int batch_size: batch size (default is 2)
        :param bool save_every_epochs: save model every epochs (default is True)
        :param int max_length: max length (default is None)
        """
        if save_every_epochs:
            self.evaluation_strategy = "epoch"
        else:
            self.evaluation_strategy = "no"
        if max_length is None:
            logging.debug('finding max_length...')
            if test_data!=None:
                self.data = train_data+test_data
            else:
                self.data = train_data
            self.max_length = max(
                [len(self.tokenizer.encode(i)) for i in self.data]
            )
        else:
            self.max_length = max_length
        
        if test_data == None:
            logging.debug('splitting data by train_size...')
            self.train_data = ListDataset(
                train_data,
                self.tokenizer,
                max_length=self.max_length,
            )
            self.train_size = int(train_size * len(self.train_data))
            self.train_data, self.test_data = random_split(
                self.train_data, [
                    self.train_size, len(self.train_data) - self.train_size
                ]
            )
        else:
            logging.debug('use train_data and test_data...')
            self.train_data = ListDataset(
                train_data,
                self.tokenizer,
                max_length=self.max_length,
            )
            self.test_data = ListDataset(
                test_data,
                self.tokenizer,
                max_length=self.max_length,
            )
        self.training_args = TrainingArguments(
            output_dir=self.model_dir,
            do_train=True,
            do_eval=True,
            evaluation_strategy="epoch",
            num_train_epochs=num_train_epochs,
            per_device_train_batch_size=batch_size,
            logging_strategy="epoch",
            save_strategy=self.evaluation_strategy,
            per_device_eval_batch_size=batch_size,
            logging_dir=logging_dir
        )
        self.train = Trainer(
            model=self.model,
            args=self.training_args,
            train_dataset=self.train_data,
            eval_dataset=self.test_data,
            data_collator=lambda data: {
                'input_ids': torch.stack([f[0] for f in data]),
                'attention_mask': torch.stack([f[1] for f in data]),
                'labels': torch.stack([f[0] for f in data])
            }
        )
        self.train.train()
        self.train.evaluate()
        self.train.save_model(self.model_dir)

    def remove_bos(self, txt: str) -> str:
        return txt.replace(self.bos_token, '')

    def remove_eos(self, txt: str) -> str:
        return txt.replace(self.eos_token, '')

    def remove_bos_eos(self, txt: str) -> str:
        return self.remove_eos(self.remove_bos(txt))

    def gen(
        self,
        text: str,
        top_k: int = 50,
        max_length: int = 89,
        top_p: float = 0.95,
        keep_bos: bool = False,
        keep_eos: bool = False,
        temperature: int = 1,
        num_return_sequences: int = 5,
        skip_special_tokens: bool = True
    ) -> List[str]:
        """
        :param str text: text
        :param int top_k: top k
        :param int max_length: max length of return sequences
        :param float top_p: top p
        :param bool keep_bos: keep beginning of a sentence
        :param bool keep_eos: keep end of a sentence
        :param int temperature: temperature
        :param int num_return_sequences: number of return sequences
        :param bool skip_special_tokens: skip special tokens
        :return: return sequences
        :rtype: List[str]
        """
        self.generated = self.tokenizer(
            text, return_tensors="pt"
        ).input_ids.to(self.device)
        self.sample_outputs = self.model.generate(
            self.generated,
            do_sample=True,
            top_k=top_k,
            max_length=max_length,
            top_p=top_p,
            temperature=temperature,
            num_return_sequences=num_return_sequences
        )
        _temp = [
            self.tokenizer.decode(
                i, skip_special_tokens=skip_special_tokens
            ) for i in self.sample_outputs
        ]
        if not keep_bos and not keep_eos:
            return [self.remove_bos_eos(i) for i in _temp]
        elif not keep_bos:
            return [self.remove_bos(i) for i in _temp]
        elif not keep_eos:
            return [self.remove_eos(i) for i in _temp]
        else:
            return _temp
