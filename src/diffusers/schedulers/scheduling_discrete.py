# Copyright 2022 Stanford University Team and The HuggingFace Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import numpy as np

from ..configuration_utils import ConfigMixin
from .scheduling_utils import SchedulerMixin


class DiscreteScheduler(SchedulerMixin, ConfigMixin):
    """
    Discrete timestep scheduler that implements either the deterministic DDIM when variance=None,
    or the stochastic DDPM scheduler.
    """

    def __init__(
        self,
        num_timesteps=1000,
        beta_min=0.0001,
        beta_max=0.02,
        beta_schedule="linear",
        clip_clean_sample=True,
        variance_type=None,
        tensor_format="np",
    ):
        super().__init__()
        self.register_to_config(
            num_timesteps=num_timesteps,
            beta_min=beta_min,
            beta_max=beta_max,
            beta_schedule=beta_schedule,
            clip_clean_sample=clip_clean_sample,
            variance_type=variance_type,
        )

        self.num_timesteps = num_timesteps
        self.clip_sample = clip_clean_sample
        self.variance_type = variance_type

        if beta_schedule == "linear":
            self.betas = np.linspace(beta_min, beta_max, num_timesteps, dtype=np.float32)
        elif beta_schedule == "scaled_linear":
            # used by the Latent Diffusion Model
            self.betas = np.linspace(beta_min**0.5, beta_max**0.5, num_timesteps, dtype=np.float32) ** 2
        elif beta_schedule == "trained":
            self.betas = None
        else:
            raise NotImplementedError(f"{beta_schedule} beta schedule is not implemented for {self.__class__}")

        self.alphas = 1.0 - self.betas
        self.alphas_cumprod = np.cumprod(self.alphas, axis=0)

        if self.variance_type == "fixed_small":
            alphas_cumprod_prev = np.concatenate(([1], self.alphas_cumprod[1:]))
            self.variance = np.sqrt((1 - alphas_cumprod_prev) / (1 - self.alphas_cumprod) * self.betas)
        elif self.variance_type == "fixed_large":
            self.variance = np.sqrt(self.betas)
        elif self.variance_type is None:
            self.variance = np.zeros(num_timesteps)
        else:
            raise NotImplementedError(f"{self.variance_type} variance is not implemented for {self.__class__}")

        self.set_format(tensor_format=tensor_format)

    def step(self, noise_prediction, noisy_sample, t, noise=None):
        """
        A single step of the denoising diffusion process.

        Args:
            noise_prediction: the noise residual predicted by the model
            noisy_sample: the noisy sample at the current timestep
            t: the current timestep
            noise: None for the deterministic DDIM, or a noise sample for the stochastic DDPM
        """
        alpha = self.alphas[t]
        beta = self.betas[t]
        alpha_cumprod = self.alphas_cumprod[t]
        alpha_cumprod_next = self.alphas_cumprod[t - 1] if t > 0 else 1

        pred_clean = (noisy_sample - self.sqrt(1 - alpha_cumprod) * noise_prediction) / self.sqrt(alpha_cumprod)
        if self.clip_sample:
            pred_clean = self.clip(pred_clean, -1, 1)

        clean_sample_coeff = (self.sqrt(alpha_cumprod_next) * beta) / (1 - alpha_cumprod)
        noisy_sample_coeff = self.sqrt(alpha) * (1 - alpha_cumprod_next) / (1 - alpha_cumprod)

        next_sample = clean_sample_coeff * pred_clean + noisy_sample_coeff * noisy_sample

        if t > 0 and noise is not None:
            next_sample += self.variance[t] * noise

        return next_sample

    def add_noise(self, clean_samples, noise, timesteps):
        """
        Add noise to the clean samples with the appropriate noise magnitude at the timesteps.
        """
        alphas_cumprod = self.alphas_cumprod[timesteps]
        alphas_cumprod = self.match_shape(alphas_cumprod, clean_samples)

        noisy_samples = self.sqrt(alphas_cumprod) * clean_samples + self.sqrt(1 - alphas_cumprod) * noise

        return noisy_samples
